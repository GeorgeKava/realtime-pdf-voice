# Gary Bot - Azure OpenAI Real-Time Financial Assistant

This project implements "Gary Bot," a web application that uses Azure OpenAI Real-Time services with WebRTC to provide a voice-interactive assistant. Gary Bot can answer questions about Apple's financials (using `FY25_Q2_Consolidated_Financial_Statements.pdf`) and Amazon's Q1 2025 earnings (using `AMZN-Q1-2025-Earnings-Release.pdf` and Azure AI Search).

## Key Features

*   **Real-Time Interaction**: Leverages Azure OpenAI Real-Time services and WebRTC for low-latency voice and text communication with the bot.
*   **Document-Based Q&A**:
    *   Answers questions about Apple's financials by directly processing `FY25_Q2_Consolidated_Financial_Statements.pdf`.
    *   Answers questions about Amazon's Q1 2025 earnings by:
        *   On startup, creating an Azure AI Search index if it doesn't exist.
        *   Processing `AMZN-Q1-2025-Earnings-Release.pdf` (chunking, embedding via Azure OpenAI) and uploading it to the search index.
        *   Performing vector search on this index when the user asks a relevant question.
*   **Function Calling**: The bot uses "function calls" (simulated via specific event handling in the client) to trigger data retrieval for both Apple and Amazon queries.

## Technologies Used

*   **Backend**:
    *   Python 3.x
    *   `aiohttp`: For asynchronous web server capabilities.
    *   `PyPDF2`: For extracting text from PDF documents.
    *   Azure SDKs:
        *   `azure-ai-ml`: (Implicitly via Azure OpenAI Real-Time services)
        *   `openai`: For interacting with Azure OpenAI embedding models.
        *   `azure-search-documents`: For Azure AI Search (index creation, document upload, vector search, semantic ranking).
*   **Frontend**:
    *   HTML, CSS, JavaScript
    *   WebRTC API: For real-time audio/data communication with the Azure services.
*   **Azure Services**:
    *   Azure OpenAI Real-Time Services (Preview): For the core bot interaction logic, text-to-speech, and speech-to-text.
    *   Azure OpenAI Service: For generating text embeddings (e.g., `text-embedding-ada-002`).
    *   Azure AI Search: For indexing and querying the Amazon earnings PDF with vector search and semantic ranking.

## Project Structure

```
.
├── AMZN-Q1-2025-Earnings-Release.pdf  # Amazon Q1 2025 earnings report
├── backend.py                         # Main Python backend (aiohttp server, Azure service logic)
├── FY25_Q2_Consolidated_Financial_Statements.pdf # Apple Q2 FY25 financial statements
├── templates/
│   └── index.html                     # Frontend HTML, JavaScript for WebRTC and bot interaction
└── README.md                          # This file
```

## Setup

1.  **Clone the repository (if applicable).**
2.  **Install Python dependencies**:
    ```bash
    pip install aiohttp PyPDF2 openai azure-core azure-search-documents
    ```
3.  **Azure Services Configuration**:
    The application requires credentials and endpoints for various Azure services. These are configured in `backend.py`. **For production, these should be set via environment variables or a secure configuration method, not hardcoded.**
    *   `API_KEY`: Azure OpenAI Real-Time service key.
    *   `AZURE_SEARCH_SERVICE_ENDPOINT`: Endpoint for your Azure AI Search service.
    *   `AZURE_SEARCH_INDEX_ADMIN_KEY`: Admin key for your Azure AI Search service (for index creation/management).
    *   `AZURE_SEARCH_API_KEY`: Query key for your Azure AI Search service.
    *   `AZURE_OPENAI_EMBEDDING_ENDPOINT`: Endpoint for your Azure OpenAI service used for embeddings.
    *   `AZURE_OPENAI_EMBEDDING_API_KEY`: API key for your Azure OpenAI service used for embeddings.
    *   `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_ID`: Deployment ID of your embedding model (e.g., `text-embedding-ada-002`).

    Update these placeholders in `backend.py` or set them as environment variables (the code currently tries to read from environment variables first, then falls back to hardcoded values).

4.  **Place PDF Files**:
    *   Ensure `FY25_Q2_Consolidated_Financial_Statements.pdf` is in the root directory.
    *   Ensure `AMZN-Q1-2025-Earnings-Release.pdf` is in the root directory.

## Running the Application

1.  **Start the backend server**:
    ```bash
    python backend.py
    ```
    The server will start, and on its first run (or if the Amazon index doesn't exist), it will attempt to create the Azure AI Search index and process/upload `AMZN-Q1-2025-Earnings-Release.pdf`. Monitor the console output for progress and any errors.

2.  **Open the frontend**:
    Open `templates/index.html` in a web browser that supports WebRTC (e.g., Chrome, Edge, Firefox).

3.  **Interact with Gary Bot**:
    *   Click the "Start Session" button.
    *   The bot should greet you.
    *   You can then ask questions like:
        *   "What were Apple's total net sales?" (triggers `fetch_pdf_document`)
        *   "What was Amazon's net income in Q1 2025?" (triggers `handle_amazon_query_tool`)

## How It Works

1.  **Session Initiation**: The frontend (`index.html`) requests an ephemeral key from the backend (`/start-session`) to connect to Azure OpenAI Real-Time services.
2.  **WebRTC Connection**: A WebRTC peer connection is established, including a data channel for sending and receiving JSON-based events.
3.  **Bot Instructions**: The client sends an initial `session.update` event to configure the bot's persona, instructions, and available tools (functions).
4.  **User Interaction**:
    *   The user speaks or types.
    *   The Azure service transcribes speech to text.
    *   The bot processes the user's query.
5.  **Function Calling**:
    *   If the bot decides to use a tool (e.g., `fetch_pdf_document` for Apple, `handle_amazon_query_tool` for Amazon), it sends a `response.function_call_arguments.done` event to the client.
    *   **Apple Financials (`fetch_pdf_document`)**:
        *   The client's `handleFetchPdfContent()` function is triggered.
        *   It calls the backend `/get-pdf-content` endpoint, which reads `FY25_Q2_Consolidated_Financial_Statements.pdf`.
        *   The PDF text is returned to the client.
        *   The client sends a `response.create` event to the bot, with the PDF content (or a summary if too long) in the `instructions`, telling the bot to use this to answer.
    *   **Amazon Earnings (`handle_amazon_query_tool`)**:
        *   The client's `handleAmazonQueryRequest()` function is triggered with the `search_query` from the bot.
        *   It calls the backend `/handle-amazon-query` endpoint.
        *   The backend embeds the `search_query` using Azure OpenAI and performs a vector search on the `amazon-earnings-q1-2025-index` in Azure AI Search.
        *   Search results are returned to the client.
        *   The client summarizes these results and sends a `response.create` event to the bot, with the summary in the `instructions`, telling the bot to use this to answer.
6.  **Bot Response**: The bot synthesizes an answer based on the information received (either from its general knowledge or the content provided via `response.create` after a function call) and sends it back to the client for text display and audio playback.

## Important Notes

*   **Error Handling**: The application includes basic error handling, but this can be further improved for robustness.
*   **Security**: The hardcoded API keys in `backend.py` are for demonstration purposes only. **Never use hardcoded keys in production.** Use environment variables, Azure Key Vault, or other secure configuration management practices.
*   **Azure Costs**: Be mindful of the costs associated with the Azure services used, especially Azure OpenAI and Azure AI Search, during development and if deployed.
*   **PDF Parsing**: The current PDF text extraction is basic (`PyPDF2`). For more complex PDFs or higher accuracy, consider more advanced parsing libraries or Azure Form Recognizer.
*   **Chunking Strategy**: The text chunking in `backend.py` for the Amazon PDF is simple. More sophisticated, semantically-aware chunking strategies could improve search relevance.
