import os
import sys
from dotenv import load_dotenv

# Ensure project root on path
sys.path.insert(0, os.path.abspath(os.getcwd()))
load_dotenv()

try:
    from google import genai
    print(f"✅ Google GenAI SDK found via 'google.genai' in Python {sys.version.split(' ')[0]}")
except ImportError as e:
    print(f"❌ Error importing genai: {e}")
    sys.exit(1)

def test_gemini():
    api_key = os.getenv("API_KEY")
    if not api_key:
        print("❌ API_KEY not found in environment.")
        return
        
    from config import Config
    client = genai.Client(api_key=api_key)
    
    model_name = Config.MODEL_NAME
    print(f"Connecting to Gemini API with model ({model_name})...")
    try:
        response = client.models.generate_content(
            model=model_name,
            contents='Respond with a single word: "Success".'
        )
        print(f"✅ Response received: {response.text.strip()}")
        print("🎉 Google GenAI is fully functional in Python 3.14!")
    except Exception as e:
        print(f"❌ API Call Failed: {e}")

if __name__ == "__main__":
    test_gemini()
