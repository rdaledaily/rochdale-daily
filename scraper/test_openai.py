import os
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")

def main():
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a test assistant."},
                {"role": "user", "content": "Say hello to Rochdale Daily."}
            ],
            max_tokens=20
        )
        print("✅ Success! GPT replied with:")
        print(response["choices"][0]["message"]["content"])
    except Exception as e:
        print("❌ Error:", e)

if __name__ == "__main__":
    main()
