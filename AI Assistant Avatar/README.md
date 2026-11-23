
# Daniel AI Assistant Avatar 🤖

Daniel AI Assistant Avatar is an AI-powered virtual assistant built using Python and Flask. It supports text-based conversations and voice interactions using AI language processing and text-to-speech technology.

## Features

- AI-powered text conversations
- Voice input using speech recognition
- AI-generated responses using Groq API
- Text-to-speech using Edge TTS
- Optional LiveAvatar integration for an animated AI avatar
- Web-based user interface
- Start and stop assistant controls

## Technologies Used

- Python
- Flask
- Groq API
- Whisper Speech Recognition
- Edge TTS
- LiveAvatar API
- HTML
- CSS
- JavaScript

## Project Structure

```text
AI Assistant Avatar/
│
├── app.py
├── .env
├── .gitignore
├── requirements.txt
├── README.md
│
└── templates/
    └── index.html
```

## Installation and Setup

### 1. Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
```

### 2. Open the project folder

```bash
cd AI-Assistant-Avatar
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file and add your own API credentials:

```env
LIVEAVATAR_API_KEY=your_liveavatar_api_key
LIVEAVATAR_AVATAR_ID=your_avatar_id
GROQ_API_KEY=your_groq_api_key
```

Never upload your `.env` file to GitHub.

### 5. Run the application

```bash
python app.py
```

Open your browser:

http://127.0.0.1:5000

## APIs Used

- Groq API – AI response generation and speech recognition
- Edge TTS – Text-to-speech conversion
- LiveAvatar API – AI avatar integration

## Author

Developed as an AI Assistant Avatar project.

## License

This project is intended for educational and development purposes.
