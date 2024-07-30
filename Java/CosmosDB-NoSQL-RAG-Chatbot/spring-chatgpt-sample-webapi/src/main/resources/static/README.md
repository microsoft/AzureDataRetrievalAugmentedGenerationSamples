# Configuration

1. Open `main.js` file with an editor
1. `CONTEXT_MESSAGE_COUNT` is the number of the latest messages to send for context
1. `DEFAULT_GREETING_MESSAGE` is the default message for a new chat
1. `API_URL` is the API endpoint for OpenAI
1. `API_HEADER` is an optional header for an API request

# Quick start

1. Go to the root folder of the `index.html`
1. Run `python -m http.server`
1. Open `http://localhost:8000` in the browser

# Data on local machine

All chat history is saved in `LocalStorage.chatHistory`

# External libs

* VueJS
* Marked

To host the external libs on your server instead of using a CDN, download the libs and upload to your server. See external lib references in `index.html` file. Do not forget to update the reference `src` to your server path as well.