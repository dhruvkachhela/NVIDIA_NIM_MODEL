import os
import time
import json
import requests
from dotenv import load_dotenv

# Load environment variables from the .env file.
# The load_dotenv() function parses the .env file and adds its variables to os.environ.
load_dotenv()

def get_api_key() -> str:
    """Retrieves the NVIDIA NIM API key from environment variables to ensure secure API requests."""
    # os.getenv retrieves the value of the environment variable. It returns None if not found.
    api_key = os.getenv("NIM_API_KEY")
    if not api_key:
        raise ValueError("NIM_API_KEY environment variable is not set. Please add it to your .env file.")
    return api_key

def fetch_models(api_key: str) -> list[str]:
    """Fetches the list of all available model IDs from the NVIDIA NIM catalog endpoint."""
    url = "https://integrate.api.nvidia.com/v1/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
    }
    
    # We send a GET request to the models list endpoint.
    # timeout=15 ensures the request doesn't hang indefinitely if the API is slow.
    response = requests.get(url, headers=headers, timeout=60)
    
    # raise_for_status() raises an exception if the HTTP request returned an unsuccessful status code (like 400 or 500).
    response.raise_for_status()
    
    data = response.json()
    
    # List comprehension: We extract the 'id' field from each model dictionary in the 'data' list.
    # We use data.get("data", []) to safely default to an empty list if "data" is missing, avoiding a KeyError.
    model_ids = [model["id"] for model in data.get("data", [])]
    return model_ids

def probe_model(api_key: str, model_id: str) -> dict:
    """Sends a minimal chat completion request to a specific model to check if it is active and responding."""
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Minimal payload containing a small request to check responsiveness.
    # We set max_tokens to 1 because we only care if the model starts responding, not about a full answer.
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Say OK"}],
        "max_tokens": 1
    }
    
    start_time = time.time()
    try:
        # We set a relatively short timeout (10 seconds) so that dead or slow models don't stall the script for too long.
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        latency = time.time() - start_time
        
        # A 200 OK status indicates the model successfully processed the request.
        if response.status_code == 200:
            return {"alive": True, "latency": latency, "error": None}
        
        # A 429 status means we are rate-limited, but the model is alive and responding.
        elif response.status_code == 429:
            return {"alive": True, "latency": latency, "error": "Rate limited (429)"}
            
        else:
            # We slice response.text to 100 characters to keep our log messages short and readable.
            return {"alive": False, "latency": latency, "error": f"HTTP {response.status_code}: {response.text[:100]}"}
            
    except requests.exceptions.Timeout:
        # Catching cases where the server took too long to reply.
        latency = time.time() - start_time
        return {"alive": False, "latency": latency, "error": "Timeout"}
        
    except requests.exceptions.RequestException as e:
        # Catching other connection-related errors (DNS failure, network down, etc.).
        latency = time.time() - start_time
        return {"alive": False, "latency": latency, "error": f"Request Exception: {str(e)}"}

def main() -> None:
    """Orchestrates the model fetching, probing, and logging process, saving working models to a JSON file."""
    print("--- Starting Phase 1: Probing Model Availability ---")
    
    try:
        api_key = get_api_key()
    except ValueError as e:
        print(f"Error: {e}")
        return
        
    print("Fetching model list from NVIDIA NIM API...")
    try:
        model_ids = fetch_models(api_key)
        print(f"Successfully retrieved {len(model_ids)} models from the catalog.")
    except Exception as e:
        print(f"Failed to fetch model list: {e}")
        return
        
    alive_models = []
    
    # We loop through all fetched models and probe each one.
    # enumerate() gives us both the index (starting at 1) and the item itself.
    for index, model_id in enumerate(model_ids, start=1):
        print(f"[{index}/{len(model_ids)}] Probing model '{model_id}'...", end="", flush=True)
        
        result = probe_model(api_key, model_id)
        
        if result["alive"]:
            # If the model is alive, we append it to our list of working models.
            alive_models.append(model_id)
            status_str = "ALIVE"
            if result["error"]:
                status_str += f" ({result['error']})"
            print(f" {status_str} (Latency: {result['latency']:.2f}s)")
        else:
            print(f" FAILED (Error: {result['error']}, Latency: {result['latency']:.2f}s)")
            
    print("\n--- Probing Complete ---")
    print(f"{len(alive_models)} of {len(model_ids)} models responded successfully.")
    
    # Save the list of working models to 'alive_models.json'.
    # Using 'with open' ensures the file is closed automatically after writing.
    output_filename = "alive_models.json"
    with open(output_filename, "w") as f:
        json.dump(alive_models, f, indent=4)
        
    print(f"Successfully wrote working models to '{output_filename}'.")

if __name__ == "__main__":
    main()
