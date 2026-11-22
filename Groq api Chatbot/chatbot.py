from groq import Groq
import os

client = Groq(
    api_key=os.environ.get("GROQ_API_KEY")
)

print(" Chatbot (Groq Streaming): Type 'quit', 'exit', or 'bye' to stop\n")

while True:
    user_input= input("You: ")
    if user_input.lower() in ["quit", "exit", "bye"]:
        print("\n Chatbot: Goodbye!")
        break
    print(" Chatbot: ",end="", flush=True)

    stream = client.chat.completions.create(
        model="openai/gpt-oss-20b",   
        messages=[
            {"role": "system", "content": "You are a helpful chatbot."},
            {"role": "user", "content": user_input}
        ],
        stream=True    
    )

    for chunk in stream:
        if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)

    print()     
