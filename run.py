import os
import time
import json
import requests
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from dotenv import load_dotenv

# Import the list of tasks from tasks.py and the grading functions from grade.py
from tasks import TASKS
import grade

# Load environment variables from the .env file
load_dotenv()

def get_api_key() -> str:
    """Retrieves the NVIDIA NIM API key from environment variables to ensure secure API requests."""
    api_key = os.getenv("NIM_API_KEY")
    if not api_key:
        raise ValueError("NIM_API_KEY environment variable is not set. Please add it to your .env file.")
    return api_key

def call_model_with_retry(api_key: str, model_id: str, prompt: str, tools: list | None = None, max_retries: int = 1) -> dict | None:
    """Calls the NVIDIA NIM chat completions API and retries up to max_retries times if a connection or rate limit error occurs."""
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}]
    }
    # If the task requires tools, we pass the tools key to the payload
    if tools:
        payload["tools"] = tools

    for attempt in range(1, max_retries + 1):
        try:
            # timeout=120 ensures we don't wait forever if a model hangs or is cold-starting
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            
            # HTTP 429 indicates rate-limiting. We sleep 5 seconds and retry.
            if response.status_code == 429:
                tqdm.write(f" [Rate limit (429) - Attempt {attempt}/{max_retries}. Sleeping 5s before retry...]")
                time.sleep(5)
                continue
                
            # Raise an HTTPError for other non-200 responses
            response.raise_for_status()
            
            # Return the parsed response dictionary
            return response.json()
            
        except (requests.exceptions.RequestException, Exception) as e:
            tqdm.write(f"\n [Attempt {attempt}/{max_retries} failed for '{model_id}': {e}]")
            if attempt < max_retries:
                # Sleep briefly before trying again
                time.sleep(2)
            else:
                tqdm.write(f" [Model '{model_id}' failed all {max_retries} attempts]")
                
    return None

def main() -> None:
    """Orchestrates the evaluation battery across working models, scores the responses, prints leaderboard tables, and saves the results."""
    print("--- Starting Phase 3: Scoring and Ranking (Parallelized) ---")
    
    try:
        api_key = get_api_key()
    except ValueError as e:
        print(f"Error: {e}")
        return

    # Load the list of models that were confirmed working in Phase 1
    input_filename = "alive_models.json"
    if not os.path.exists(input_filename):
        print(f"Error: '{input_filename}' not found. Please run probe.py first to check model availability.")
        return

    with open(input_filename, "r") as f:
        alive_models = json.load(f)

    if not alive_models:
        print("No alive models found to evaluate. Exiting.")
        return

    print(f"Found {len(alive_models)} working models in '{input_filename}'.")

    # Optional testing limit: we can set MAX_EVAL_MODELS in .env to evaluate a subset of models
    max_eval = os.getenv("MAX_EVAL_MODELS")
    if max_eval:
        try:
            limit = int(max_eval)
            alive_models = alive_models[:limit]
            print(f"DEBUG: Limiting evaluation to the first {limit} models (MAX_EVAL_MODELS={limit}).")
        except ValueError:
            pass

    # Distinct categories we are evaluating
    categories = ["coding", "math", "writing", "tool_calling"]
    
    # Initialize a nested dictionary to hold raw scores, latencies, and counts for each model and category
    model_results = {}
    for model_id in alive_models:
        model_results[model_id] = {
            "scores": {cat: 0.0 for cat in categories},
            "latencies": {cat: 0.0 for cat in categories},
            "counts": {cat: 0 for cat in categories}
        }

    # Parallel processing configuration
    MAX_WORKERS = 3
    active_workers = ["Idle"] * MAX_WORKERS
    worker_ids = queue.Queue()
    for i in range(MAX_WORKERS):
        worker_ids.put(i)

    results_lock = threading.Lock()
    status_lock = threading.Lock()

    # Total evaluations = models * tasks
    total_evals = len(alive_models) * len(TASKS)
    
    # Initialize tqdm progress bar
    pbar = tqdm(total=total_evals, desc="Active: Idle | Idle | Idle", unit="task")

    def evaluate_model(model_id: str) -> None:
        worker_id = worker_ids.get()
        
        # Shorten model name for console display
        short_name = model_id.split("/")[-1] if "/" in model_id else model_id
        if len(short_name) > 15:
            short_name = short_name[:12] + "..."
            
        with status_lock:
            active_workers[worker_id] = short_name
            pbar.set_description(f"Active: {' | '.join(active_workers)}")
            
        try:
            for task in TASKS:
                task_id = task["id"]
                category = task["category"]
                prompt = task["prompt"]
                grader_name = task["grader"]
                expected = task["expected"]
                tools = task["tools"]
                
                start_time = time.time()
                response_data = call_model_with_retry(api_key, model_id, prompt, tools)
                latency = time.time() - start_time
                
                score = 0.0
                status_str = "FAIL"
                passed = False
                details_str = ""
                
                if response_data is None:
                    status_str = "TIMEOUT"
                else:
                    choices = response_data.get("choices", [])
                    response_text = ""
                    if choices:
                        response_text = choices[0].get("message", {}).get("content", "") or ""

                    # Look up the grading function dynamically from our grade module using getattr
                    grader_func = getattr(grade, grader_name, None)
                    if grader_func is None:
                        status_str = "GRADER ERROR"
                    else:
                        try:
                            # The tool-calling grader needs the whole response dict, others just need text
                            if category == "tool_calling":
                                passed = grader_func(response_data, expected)
                            else:
                                passed = grader_func(response_text, expected)
                            
                            score = 1.0 if passed else 0.0
                            status_str = "PASS" if passed else "FAIL"
                            
                            if not passed:
                                # We construct details about the failure to help diagnose the issue
                                details_lines = []
                                details_lines.append(f"   --> Model Output: {repr(response_text[:250])}")
                                if category == "tool_calling":
                                    message_obj = choices[0].get("message", {}) if choices else {}
                                    details_lines.append(f"   --> Expected Tool Calls: {expected.get('required_calls')}")
                                    details_lines.append(f"   --> Actual Tool Calls: {message_obj.get('tool_calls')}")
                                else:
                                    details_lines.append(f"   --> Expected: {expected}")
                                details_str = "\n".join(details_lines)
                        except Exception as e:
                            status_str = f"ERROR in grading: {e}"
                
                # Record scores (thread-safe)
                with results_lock:
                    model_results[model_id]["scores"][category] += score
                    model_results[model_id]["latencies"][category] += latency
                    model_results[model_id]["counts"][category] += 1
                
                # Log results on a new row in columns: model name, category, status, latency
                log_line = f"{model_id:<45} | {category:<12} | {status_str:<12} | {latency:.2f}s"
                if details_str:
                    log_line += f"\n{details_str}"
                tqdm.write(log_line)
                
                # Update overall progress bar
                pbar.update(1)
                
                # Sleep briefly to avoid aggressive requests on the free tier
                time.sleep(0.5)
                
        finally:
            with status_lock:
                active_workers[worker_id] = "Idle"
                pbar.set_description(f"Active: {' | '.join(active_workers)}")
            worker_ids.put(worker_id)

    # Execute model evaluations concurrently across 3 workers
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(evaluate_model, alive_models)

    pbar.close()


    # Compute averages and build the final summary dictionary
    summary_results = {}
    for model_id, data in model_results.items():
        summary_results[model_id] = {}
        for cat in categories:
            count = data["counts"][cat]
            total_score = data["scores"][cat]
            total_latency = data["latencies"][cat]
            
            # Compute average score and average latency, defaulting to 0 if count is 0
            avg_score = (total_score / count) if count > 0 else 0.0
            avg_latency = (total_latency / count) if count > 0 else 0.0
            
            summary_results[model_id][cat] = {
                "score": avg_score,
                "latency": avg_latency
            }

    # Write the aggregated results to results.json
    output_filename = "results.json"
    with open(output_filename, "w") as f:
        json.dump(summary_results, f, indent=4)
        
    print(f"\nSuccessfully wrote results to '{output_filename}'.")

    # Print the leaderboard tables for each category
    print("\n" + "=" * 80)
    print("                     EVALUATION LEADERBOARDS")
    print("=" * 80)
    
    for cat in categories:
        print(f"\n--- Category: {cat.upper()} ---")
        print(f"{'Rank':<5} | {'Model Name':<50} | {'Score':<6} | {'Avg Latency':<11}")
        print("-" * 80)
        
        # Sort the models by score descending, and then by latency ascending (tie breaker)
        # lambda m: (score, -latency) ensures higher score is first, and for matching scores, lower latency is first
        sorted_models = sorted(
            summary_results.keys(),
            key=lambda m: (summary_results[m][cat]["score"], -summary_results[m][cat]["latency"]),
            reverse=True
        )
        
        for rank, model_id in enumerate(sorted_models, start=1):
            score = summary_results[model_id][cat]["score"]
            latency = summary_results[model_id][cat]["latency"]
            # Formatting floats to 2 decimal places using .2f
            print(f"{rank:<5} | {model_id:<50} | {score:<6.2f} | {latency:<10.2f}s")
            
    # --- Phase 5: Output Routing Table ---
    print("\n" + "=" * 80)
    print("                     GENERATING ROUTER CONFIGURATION")
    print("=" * 80)
    
    router_config = {}
    for cat in categories:
        # Sort the models for this category using the same keys: score (descending) and latency (ascending)
        sorted_models = sorted(
            summary_results.keys(),
            key=lambda m: (summary_results[m][cat]["score"], -summary_results[m][cat]["latency"]),
            reverse=True
        )
        if sorted_models:
            # The first model in the sorted list is the top performer
            router_config[cat] = sorted_models[0]
        else:
            router_config[cat] = None
            
    # Save the selected routes to router.json
    router_filename = "router.json"
    with open(router_filename, "w") as f:
        json.dump(router_config, f, indent=4)
        
    print(f"Successfully wrote router configuration to '{router_filename}'.")
    print("Selected routing map:")
    for cat, model in router_config.items():
        print(f"  - {cat:<13} -> {model}")
        
    # --- Generate CSV and Markdown Leaderboards for AI Search Compatibility ---
    import csv
    
    # 1. Export to results.csv
    csv_filename = "results.csv"
    try:
        with open(csv_filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Model", "Category", "Score", "Latency"])
            for model_id, cat_data in summary_results.items():
                for cat, stats in cat_data.items():
                    # Format float values to 4 decimal places for CSV precision
                    writer.writerow([model_id, cat, f"{stats['score']:.4f}", f"{stats['latency']:.4f}"])
        print(f"Successfully wrote CSV results to '{csv_filename}'.")
    except Exception as e:
        print(f"Failed to write CSV results: {e}")

    # 2. Export to leaderboard.md
    md_filename = "leaderboard.md"
    try:
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write("# NVIDIA NIM Evaluation Leaderboard\n\n")
            f.write("Created and Maintained by **[dhruvkachhela](https://github.com/dhruvkachhela)**.\n\n")
            f.write("This table is automatically updated by the automated weekly cron job. It displays performance ratings and latencies for all active models across various tasks.\n\n")
            
            for cat in categories:
                f.write(f"## {cat.capitalize()} Leaderboard\n\n")
                f.write("| Rank | Model Name | Score | Avg Latency |\n")
                f.write("| :--- | :--- | :--- | :--- |\n")
                
                sorted_models = sorted(
                    summary_results.keys(),
                    key=lambda m: (summary_results[m][cat]["score"], -summary_results[m][cat]["latency"]),
                    reverse=True
                )
                for rank, model_id in enumerate(sorted_models, start=1):
                    score = summary_results[model_id][cat]["score"]
                    latency = summary_results[model_id][cat]["latency"]
                    f.write(f"| {rank} | `{model_id}` | {score:.2f} | {latency:.2f}s |\n")
                f.write("\n")
        print(f"Successfully wrote Markdown leaderboard to '{md_filename}'.")
    except Exception as e:
        print(f"Failed to write Markdown leaderboard: {e}")
        
    # 3. Update README.md with Live Benchmark Tables, Catalog, and Recommendations (AI-Search discoverability)
    readme_filename = "README.md"
    try:
        if os.path.exists(readme_filename):
            with open(readme_filename, "r", encoding="utf-8") as f:
                readme_content = f.read()
                
            # A. Generate Benchmark Tables
            benchmark_md = "<!-- BENCHMARK_START -->\n"
            for cat in categories:
                # Capitalize category name for presentation
                cat_display = cat.replace("_", " ").title()
                benchmark_md += f"### {cat_display} Benchmark (Task Fit & Speed)\n\n"
                benchmark_md += f"| Rank | Supported Models | Score (Task Fit) | Avg Latency (Speed) |\n"
                benchmark_md += f"| :--- | :--- | :--- | :--- |\n"
                
                sorted_models = sorted(
                    summary_results.keys(),
                    key=lambda m: (summary_results[m][cat]["score"], -summary_results[m][cat]["latency"]),
                    reverse=True
                )
                for rank, model_id in enumerate(sorted_models, start=1):
                    score = summary_results[model_id][cat]["score"]
                    latency = summary_results[model_id][cat]["latency"]
                    benchmark_md += f"| {rank} | `{model_id}` | {score:.2f} | {latency:.2f}s |\n"
                benchmark_md += "\n"
            benchmark_md += "<!-- BENCHMARK_END -->"
            
            # B. Generate Active Models Catalog
            alive_models_md = "<!-- ALIVE_MODELS_START -->\n"
            alive_models_md += f"The following **{len(alive_models)} models** are probed and verified as actively responding on the NVIDIA NIM free-tier:\n\n"
            alive_models_md += "<details>\n"
            alive_models_md += f"<summary><b>Click to expand full list of active models ({len(alive_models)})</b></summary>\n\n"
            for model_id in sorted(alive_models):
                label = ""
                if "safety" in model_id.lower() or "guard" in model_id.lower():
                    label = " *(moderation only)*"
                elif "translate" in model_id.lower():
                    label = " *(translation only)*"
                elif "gliner" in model_id.lower():
                    label = " *(specialized task)*"
                alive_models_md += f"*   `{model_id}`{label}\n"
            alive_models_md += "\n</details>\n<!-- ALIVE_MODELS_END -->"
            
            # C. Generate Model Recommendations & Fitness Guide
            cat_notes = {
                "coding": "Excellent instruction-following, outputs code cleanly inside blocks, and correctly solves programming test cases.",
                "math": "Strong reasoning abilities for seating constraints, logic puzzles, and quadratic equation derivations.",
                "writing": "Adheres strictly to word count bounds and list bullet formats with minimal latency.",
                "tool_calling": "Natively triggers functional tools with correct parameter names and values."
            }
            cat_icons = {
                "coding": "💻 Coding",
                "math": "🧮 Math & Logic",
                "writing": "✍️ General Writing",
                "tool_calling": "🔌 Tool Calling"
            }
            
            recommendations_md = "<!-- RECOMMENDATIONS_START -->\n"
            recommendations_md += "Based on the latest evaluation data, different models exhibit distinct strengths. Use this guide to select the best model for your workload:\n\n"
            recommendations_md += "| Category | Recommended Model | Best Accuracy | Typical Latency | Suitability Notes |\n"
            recommendations_md += "| :--- | :--- | :---: | :---: | :--- |\n"
            for cat in categories:
                sorted_models = sorted(
                    summary_results.keys(),
                    key=lambda m: (summary_results[m][cat]["score"], -summary_results[m][cat]["latency"]),
                    reverse=True
                )
                if sorted_models:
                    m1 = sorted_models[0]
                    score1 = summary_results[m1][cat]["score"]
                    lat1 = summary_results[m1][cat]["latency"]
                    m_str = f"`{m1}`"
                    # Add secondary model if it shares identical top score and similar latency
                    if len(sorted_models) > 1:
                        m2 = sorted_models[1]
                        score2 = summary_results[m2][cat]["score"]
                        lat2 = summary_results[m2][cat]["latency"]
                        if score2 == score1 and abs(lat2 - lat1) < 2.0:
                            m_str += f"<br>`{m2}`"
                    recommendations_md += f"| **{cat_icons[cat]}** | {m_str} | **{score1:.2f}** | **~{lat1:.2f}s** | {cat_notes[cat]} |\n"
                else:
                    recommendations_md += f"| **{cat_icons[cat]}** | None | N/A | N/A | No active models found for this category |\n"
            
            recommendations_md += "\n### ⚠️ Important Usage Warnings\n"
            recommendations_md += "- **Avoid Moderation Models for Tasks**: Do not route general coding, writing, or math queries to `llama-guard-4-12b` or any `content-safety` / `safety-guard` model. They only output safety classifications and will score 0 on general benchmarks.\n"
            recommendations_md += "- **Vision-Instruct Latency spikes**: `meta/llama-3.2-11b-vision-instruct` performs well but can suffer from severe response delays under queue load.\n"
            recommendations_md += "- **Specialized Domain Models**: Models like `nvidia/riva-translate` (translation only) and `nvidia/gliner-pii` (entity masking only) should not be used for generic chat or reasoning.\n"
            recommendations_md += "<!-- RECOMMENDATIONS_END -->"
            
            # Replace whatever is currently in the placeholder with the new content
            import re
            updated_content = re.sub(r"<!-- BENCHMARK_START -->.*?<!-- BENCHMARK_END -->", benchmark_md, readme_content, flags=re.DOTALL)
            updated_content = re.sub(r"<!-- ALIVE_MODELS_START -->.*?<!-- ALIVE_MODELS_END -->", alive_models_md, updated_content, flags=re.DOTALL)
            updated_content = re.sub(r"<!-- RECOMMENDATIONS_START -->.*?<!-- RECOMMENDATIONS_END -->", recommendations_md, updated_content, flags=re.DOTALL)
            
            with open(readme_filename, "w", encoding="utf-8") as f:
                f.write(updated_content)
            print(f"Successfully updated benchmark tables, active catalog, and recommendations directly inside '{readme_filename}'.")
    except Exception as e:
        print(f"Failed to update README.md with benchmark results: {e}")
        
if __name__ == "__main__":
    main()
