import os
import time
import json
import requests
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
            # timeout=15 ensures we don't wait forever if a model hangs
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            
            # HTTP 429 indicates rate-limiting. We sleep 5 seconds and retry.
            if response.status_code == 429:
                print(f" [Rate limit (429) - Attempt {attempt}/{max_retries}. Sleeping 5s before retry...]")
                time.sleep(5)
                continue
                
            # Raise an HTTPError for other non-200 responses
            response.raise_for_status()
            
            # Return the parsed response dictionary
            return response.json()
            
        except (requests.exceptions.RequestException, Exception) as e:
            print(f"\n [Attempt {attempt}/{max_retries} failed for '{model_id}': {e}]")
            if attempt < max_retries:
                # Sleep briefly before trying again
                time.sleep(2)
            else:
                print(f" [Model '{model_id}' failed all {max_retries} attempts]")
                
    return None

def main() -> None:
    """Orchestrates the evaluation battery across working models, scores the responses, prints leaderboard tables, and saves the results."""
    print("--- Starting Phase 3: Scoring and Ranking ---")
    
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

    # Main evaluation loop
    for model_idx, model_id in enumerate(alive_models, start=1):
        print(f"\n==========================================")
        print(f"[{model_idx}/{len(alive_models)}] Evaluating: {model_id}")
        print(f"==========================================")
        
        for task in TASKS:
            task_id = task["id"]
            category = task["category"]
            prompt = task["prompt"]
            grader_name = task["grader"]
            expected = task["expected"]
            tools = task["tools"]
            
            print(f"Running '{task_id}'...", end="", flush=True)
            
            start_time = time.time()
            response_data = call_model_with_retry(api_key, model_id, prompt, tools)
            latency = time.time() - start_time
            
            score = 0.0
            if response_data is None:
                print(" FAIL (Connection Error / Timeout)")
            else:
                choices = response_data.get("choices", [])
                response_text = ""
                if choices:
                    response_text = choices[0].get("message", {}).get("content", "") or ""

                # Look up the grading function dynamically from our grade module using getattr
                grader_func = getattr(grade, grader_name, None)
                if grader_func is None:
                    print(f" ERROR (Grader '{grader_name}' not found)")
                else:
                    try:
                        # The tool-calling grader needs the whole response dict, others just need text
                        if category == "tool_calling":
                            passed = grader_func(response_data, expected)
                        else:
                            passed = grader_func(response_text, expected)
                        
                        score = 1.0 if passed else 0.0
                        print(" PASS" if passed else " FAIL")
                    except Exception as e:
                        print(f" ERROR in grading: {e}")
            
            # Record scores
            model_results[model_id]["scores"][category] += score
            model_results[model_id]["latencies"][category] += latency
            model_results[model_id]["counts"][category] += 1
            
            # Sleep briefly to avoid aggressive requests on the free tier
            time.sleep(0.5)

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
        
if __name__ == "__main__":
    main()
