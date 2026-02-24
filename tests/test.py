from google import genai

client = genai.Client(api_key="AIzaSyBHzum-zCVMbOtf8nFzIKBhjAydnsJyPv0")

for m in client.models.list():
    print(m.name)