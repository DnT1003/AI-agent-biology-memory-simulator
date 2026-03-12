
from google import genai
import os
from dotenv import load_dotenv

def list_models_all():
    load_dotenv()
    api_key = os.getenv("API_KEY")
    
    print("=== API: v1 ===")
    client_v1 = genai.Client(api_key=api_key)
    for m in client_v1.models.list():
        if "embed" in m.name.lower():
            print(f"{m.name} | {m.supported_actions}")
            
    print("\n=== API: v1beta1 ===")
    # Note: v1beta is often reached via http_options
    client_beta = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})
    for m in client_beta.models.list():
        if "embed" in m.name.lower():
            print(f"{m.name} | {m.supported_actions}")

if __name__ == "__main__":
    list_models_all()
