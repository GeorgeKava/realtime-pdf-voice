import os
import logging
from dotenv import load_dotenv # ADDED
from aiohttp import web
import aiohttp
import asyncio
import PyPDF2 # Added import for PDF processing
import re # For text chunking
import uuid # For generating document IDs

# Azure SDK imports
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.models import VectorizedQuery
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    SimpleField,
    SearchableField,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    SemanticSearch,
    SemanticConfiguration,
    SemanticPrioritizedFields,
    SemanticField
)
from openai import AsyncAzureOpenAI # For embeddings
from config import SESSION_CONFIGURATION # Added import

# Setup logging first (MOVED AND ENHANCED from later in the file)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Configuration variables loaded from .env
# Ensure these variables are set in your .env file
WEBRTC_URL = os.environ.get("WEBRTC_URL")
SESSIONS_URL = os.environ.get("SESSIONS_URL")
API_KEY = os.environ.get("API_KEY")
DEPLOYMENT = os.environ.get("DEPLOYMENT")
VOICE = os.environ.get("VOICE")

# Azure AI Search Configuration
AZURE_SEARCH_SERVICE_ENDPOINT = os.environ.get("AZURE_SEARCH_SERVICE_ENDPOINT")
AZURE_SEARCH_INDEX_ADMIN_KEY = os.environ.get("AZURE_SEARCH_INDEX_ADMIN_KEY")
AZURE_SEARCH_API_KEY = os.environ.get("AZURE_SEARCH_API_KEY")
AMAZON_INDEX_NAME = os.environ.get("AMAZON_INDEX_NAME", "amazon-earnings-q1-2025-index")
AMAZON_PDF_PATH = os.environ.get("AMAZON_PDF_PATH", "AMZN-Q1-2025-Earnings-Release.pdf") # Relative to backend.py

# Azure OpenAI Embedding Configuration
AZURE_OPENAI_EMBEDDING_ENDPOINT = os.environ.get("AZURE_OPENAI_EMBEDDING_ENDPOINT")
AZURE_OPENAI_EMBEDDING_API_KEY = os.environ.get("AZURE_OPENAI_EMBEDDING_API_KEY")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_ID = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_ID")
AZURE_OPENAI_EMBEDDING_API_VERSION = os.environ.get("AZURE_OPENAI_EMBEDDING_API_VERSION")

# Load EMBEDDING_DIMENSIONS as an integer, with a default if not specified or invalid
EMBEDDING_DIMENSIONS_STR = os.environ.get("EMBEDDING_DIMENSIONS")
if EMBEDDING_DIMENSIONS_STR is None:
    logger.info("EMBEDDING_DIMENSIONS not found in .env, using default 1536.")
    EMBEDDING_DIMENSIONS = 1536
else:
    try:
        EMBEDDING_DIMENSIONS = int(EMBEDDING_DIMENSIONS_STR)
    except ValueError:
        logger.warning(f"Invalid value for EMBEDDING_DIMENSIONS ('{EMBEDDING_DIMENSIONS_STR}') in .env, using default 1536.")
        EMBEDDING_DIMENSIONS = 1536

# Check for critical missing environment variables
critical_vars_map = {
    "WEBRTC_URL": WEBRTC_URL,
    "SESSIONS_URL": SESSIONS_URL,
    "API_KEY": API_KEY,
    "DEPLOYMENT": DEPLOYMENT,
    "VOICE": VOICE,
    "AZURE_SEARCH_SERVICE_ENDPOINT": AZURE_SEARCH_SERVICE_ENDPOINT,
    "AZURE_SEARCH_INDEX_ADMIN_KEY": AZURE_SEARCH_INDEX_ADMIN_KEY,
    "AZURE_SEARCH_API_KEY": AZURE_SEARCH_API_KEY,
    "AZURE_OPENAI_EMBEDDING_ENDPOINT": AZURE_OPENAI_EMBEDDING_ENDPOINT,
    "AZURE_OPENAI_EMBEDDING_API_KEY": AZURE_OPENAI_EMBEDDING_API_KEY,
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_ID": AZURE_OPENAI_EMBEDDING_DEPLOYMENT_ID,
    "AZURE_OPENAI_EMBEDDING_API_VERSION": AZURE_OPENAI_EMBEDDING_API_VERSION
}

missing_critical_vars = [var_name for var_name, var_value in critical_vars_map.items() if not var_value]

if missing_critical_vars:
    error_message = f"Critical environment variables missing or empty: {', '.join(missing_critical_vars)}. Please define them in the .env file."
    logger.error(error_message)
    # For a production system, you might want to raise an exception here to halt startup:
    # raise EnvironmentError(error_message)

# --- Helper Functions for Azure AI Search & Embeddings (no changes here) ---
async def get_embedding_async(text: str, aoai_client: AsyncAzureOpenAI):
    """Generates an embedding for the given text using Azure OpenAI."""
    logger.info(f"Attempting to generate embedding for text (first 100 chars): '{text[:100]}'")
    if not text or not text.strip():
        logger.error("Cannot generate embedding for empty or whitespace-only text.")
        # Raising a ValueError to make it explicit during debugging.
        # Depending on desired behavior, you might return None or an empty list.
        raise ValueError("Input text for embedding cannot be empty or just whitespace.")
    try:
        response = await aoai_client.embeddings.create(
            input=[text], # Input is a list of strings
            model=AZURE_OPENAI_EMBEDDING_DEPLOYMENT_ID,
        )
        return response.data[0].embedding
    except Exception as e:
        # Log the problematic text snippet along with the error
        logger.error(f"Error generating embedding for text snippet '{text[:100]}...': {e}")
        raise

def chunk_text(text: str, max_chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """
    Simple text chunker. Splits text into smaller pieces for processing.
    This implementation first splits by paragraphs, then by size if paragraphs are too large.

    Args:
        text: The input text to chunk.
        max_chunk_size: The maximum size of each chunk.
        overlap: The number of characters to overlap between chunks from the same large paragraph.

    Returns:
        A list of text chunks.
    """
    # Using paragraphs as a basis, then splitting if too long.
    paragraphs = re.split(r'\\n\\s*\\n', text)
    chunks = []
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        if len(paragraph) <= max_chunk_size:
            chunks.append(paragraph)
        else:
            # Simple split for oversized paragraphs
            start = 0
            while start < len(paragraph):
                end = min(start + max_chunk_size, len(paragraph))
                chunks.append(paragraph[start:end])
                start += max_chunk_size - overlap
                if start >= len(paragraph): # ensure last part is captured
                    break
    return [chunk for chunk in chunks if chunk.strip()]


async def create_amazon_index_if_not_exists_async(search_index_client: SearchIndexClient):
    """
    Creates the Azure AI Search index for Amazon documents if it doesn't already exist.
    The index is configured for vector search and semantic ranking.

    Args:
        search_index_client: An asynchronous SearchIndexClient instance.

    Returns:
        True if the index was newly created, False if it already existed.
    """
    try:
        await search_index_client.get_index(AMAZON_INDEX_NAME)
        logger.info(f"Index '{AMAZON_INDEX_NAME}' already exists.")
        return False # Indicates index already existed
    except Exception: # Typically ResourceNotFoundError if index doesn't exist
        logger.info(f"Index '{AMAZON_INDEX_NAME}' not found. Creating new index...")
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True, sortable=True, filterable=True, facetable=True),
            SearchableField(name="content", type=SearchFieldDataType.String, sortable=False, filterable=False, facetable=False),
            SearchField(name="embedding", type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                        searchable=True, vector_search_dimensions=EMBEDDING_DIMENSIONS, vector_search_profile_name="my-vector-profile"),
            SimpleField(name="sourcefile", type=SearchFieldDataType.String, filterable=True, facetable=True)
        ]

        vector_search = VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="my-hnsw-config")],
            profiles=[VectorSearchProfile(name="my-vector-profile", algorithm_configuration_name="my-hnsw-config")]
        )

        semantic_search = SemanticSearch(configurations=[
            SemanticConfiguration(
                name="my-semantic-config",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=None, # No specific title field in our chunks
                    content_fields=[SemanticField(field_name="content")]
                )
            )
        ])

        index = SearchIndex(
            name=AMAZON_INDEX_NAME,
            fields=fields,
            vector_search=vector_search,
            semantic_search=semantic_search
        )
        await search_index_client.create_index(index)
        logger.info(f"Index '{AMAZON_INDEX_NAME}' created successfully.")
        return True # Indicates index was newly created

async def process_and_upload_amazon_pdf_async(search_client: SearchClient, aoai_client: AsyncAzureOpenAI):
    """
    Reads text from the Amazon PDF specified by AMAZON_PDF_PATH,
    chunks the text, generates embeddings for each chunk using Azure OpenAI,
    and uploads the documents (chunks with embeddings) to the Azure AI Search index.

    Args:
        search_client: An asynchronous SearchClient instance for uploading documents.
        aoai_client: An asynchronous AsyncAzureOpenAI client for generating embeddings.
    """
    logger.info(f"Processing PDF: {AMAZON_PDF_PATH}")
    pdf_text = ""
    try:
        with open(AMAZON_PDF_PATH, 'rb') as pdf_file_obj:
            pdf_reader = PyPDF2.PdfReader(pdf_file_obj)
            for page_num in range(len(pdf_reader.pages)):
                page_obj = pdf_reader.pages[page_num]
                pdf_text += page_obj.extract_text()
        
        if not pdf_text.strip():
            logger.warning(f"No text extracted from PDF: {AMAZON_PDF_PATH}")
            return

        logger.info(f"Extracted text from {AMAZON_PDF_PATH} (length: {len(pdf_text)}). Chunking and embedding...")
        
        text_chunks = chunk_text(pdf_text)
        documents_to_upload = []
        for i, chunk in enumerate(text_chunks):
            embedding = await get_embedding_async(chunk, aoai_client)
            documents_to_upload.append({
                "id": str(uuid.uuid4()), # Generate unique ID for each chunk
                "content": chunk,
                "embedding": embedding,
                "sourcefile": AMAZON_PDF_PATH
            })
            if (i + 1) % 10 == 0: # Log progress
                 logger.info(f"Embedded {i+1}/{len(text_chunks)} chunks...")

        if documents_to_upload:
            await search_client.upload_documents(documents=documents_to_upload)
            logger.info(f"Successfully uploaded {len(documents_to_upload)} documents from '{AMAZON_PDF_PATH}' to index '{AMAZON_INDEX_NAME}'.")
        else:
            logger.info(f"No documents to upload from '{AMAZON_PDF_PATH}'.")

    except FileNotFoundError:
        logger.error(f"Amazon PDF file not found: {AMAZON_PDF_PATH}")
    except Exception as e:
        logger.exception(f"Error processing and uploading Amazon PDF {AMAZON_PDF_PATH}:")

# --- Application Startup Task for Amazon Index ---
async def initialize_amazon_search_index(app_obj):
    """
    Application startup task.
    Checks if the Azure AI Search index for Amazon data exists. If not, it creates it.
    If the index is newly created, it processes and uploads the Amazon PDF content.
    Sets 'amazon_index_initialized' in the application object.

    Args:
        app_obj: The aiohttp application object.
    """
    logger.info("Initializing Amazon Search Index on application startup...")
    search_admin_credential = AzureKeyCredential(AZURE_SEARCH_INDEX_ADMIN_KEY)
    search_index_client = SearchIndexClient(endpoint=AZURE_SEARCH_SERVICE_ENDPOINT, credential=search_admin_credential)
    aoai_client = AsyncAzureOpenAI(
        api_key=AZURE_OPENAI_EMBEDDING_API_KEY,
        azure_endpoint=AZURE_OPENAI_EMBEDDING_ENDPOINT,
        api_version=AZURE_OPENAI_EMBEDDING_API_VERSION
    )

    async with search_index_client, aoai_client:
        try:
            index_newly_created = await create_amazon_index_if_not_exists_async(search_index_client)
            if index_newly_created:
                logger.info(f"Index '{AMAZON_INDEX_NAME}' was newly created. Processing and uploading PDF content...")
                # Use a SearchClient with admin credentials for uploading documents
                upload_search_client = SearchClient(
                    endpoint=AZURE_SEARCH_SERVICE_ENDPOINT, 
                    index_name=AMAZON_INDEX_NAME, 
                    credential=search_admin_credential
                )
                async with upload_search_client:
                    await process_and_upload_amazon_pdf_async(upload_search_client, aoai_client)
                app_obj['amazon_index_initialized'] = True # Mark as initialized
                logger.info("Amazon PDF processing and upload complete.")
            else:
                # Index already existed, assume it's populated correctly or manage updates separately if needed.
                logger.info(f"Index '{AMAZON_INDEX_NAME}' already exists. Skipping PDF processing and upload.")
                app_obj['amazon_index_initialized'] = True # Mark as initialized
        except Exception as e:
            logger.exception("Failed to initialize Amazon Search Index during startup:")
            app_obj['amazon_index_initialized'] = False # Mark as failed

routes = web.RouteTableDef()

@routes.get('/')
async def index(request):
    """Serves the main HTML page."""
    return web.FileResponse('templates/index.html')

@routes.get('/favicon.ico')
async def favicon(request):
    """Handles requests for favicon.ico to prevent 404 errors."""
    return web.Response(status=204) # Send No Content

@routes.get('/app.js') # ADDED ROUTE
async def serve_app_js(request): # ADDED HANDLER
    """Serves the app.js file.""" # ADDED DOCSTRING
    return web.FileResponse('static/app.js') # Corrected path to static/app.js

@routes.get('/get-session-configuration') # ADDED ROUTE
async def get_session_configuration(request): # ADDED HANDLER
    """Serves the session configuration from config.py.""" # ADDED DOCSTRING
    logger.info("Serving session configuration.")
    return web.json_response(SESSION_CONFIGURATION)

@routes.post('/start-session')
async def start_session(request):
    """
    Handles the /start-session POST request.
    Calls the Azure OpenAI Real-Time Sessions API to start a new session
    and returns the session ID and ephemeral client secret (key) to the frontend.
    """
    payload = {
        "model": DEPLOYMENT,
        "voice": VOICE
    }
    headers = {
        "api-key": API_KEY,
        "Content-Type": "application/json"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SESSIONS_URL, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Session API error: {error_text}")
                    return web.json_response({"error": "API request failed", "details": error_text}, status=500)
                data = await resp.json()
                session_id = data.get("id")
                ephemeral_key = data.get("client_secret", {}).get("value")
                logger.info(f"Ephemeral key: {ephemeral_key}")
                return web.json_response({"session_id": session_id, "ephemeral_key": ephemeral_key})
    except Exception as e:
        logger.exception("Error fetching ephemeral key:")
        return web.json_response({"error": str(e)}, status=500)

@routes.post('/get-pdf-content')
async def get_pdf_content(request):
    """
    Handles the /get-pdf-content POST request.
    Reads the specified Apple financial PDF (`FY25_Q2_Consolidated_Financial_Statements.pdf`),
    extracts all text from it, and returns the text to the frontend.
    """
    # In a real application, you might take a filename or specific query,
    # but for now, we'll hardcode the PDF and return all its text.
    pdf_path = "FY25_Q2_Consolidated_Financial_Statements.pdf"
    pdf_text = ""
    print(f"PDF path: {pdf_path}")
    try:
        with open(pdf_path, 'rb') as pdf_file_obj:
            pdf_reader = PyPDF2.PdfReader(pdf_file_obj)
            for page_num in range(len(pdf_reader.pages)):
                page_obj = pdf_reader.pages[page_num]
                pdf_text += page_obj.extract_text()
        

        if not pdf_text:
            logger.warning(f"No text extracted from PDF: {pdf_path}")
            # Return empty if no text, or a specific message
            return web.json_response({"pdf_text": "", "message": "No text could be extracted from the PDF."}, status=200)
            
        logger.info(f"Successfully extracted text from {pdf_path} (length: {len(pdf_text)}).")
        print(f"Extracted text length: {len(pdf_text)}")
        return web.json_response({"pdf_text": pdf_text})
    except FileNotFoundError:
        logger.error(f"PDF file not found: {pdf_path}")
        return web.json_response({"error": "PDF file not found."}, status=404)
    except Exception as e:
        logger.exception(f"Error processing PDF {pdf_path}:")
        return web.json_response({"error": f"Could not process PDF: {str(e)}"}, status=500)

@routes.post('/webrtc-sdp')
async def webrtc_sdp(request):
    """
    Handles the /webrtc-sdp POST request for WebRTC signaling.
    Receives the SDP offer and ephemeral key from the client,
    forwards the SDP offer to the Azure Real-Time RTC service,
    and returns the SDP answer from Azure back to the client.
    """
    data = await request.json()
    ephemeral_key = data['ephemeral_key']
    offer_sdp = data['offer_sdp']
    headers = {
        "Authorization": f"Bearer {ephemeral_key}",
        "Content-Type": "application/sdp"
    }
    url = f"{WEBRTC_URL}?model={DEPLOYMENT}"

#print() in yellow
    print(f"WebRTC SDP exchange URL: {url}")
    print(f"WebRTC SDP exchange headers: {headers}")
    # print(f"WebRTC SDP exchange offer_sdp: {offer_sdp}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=offer_sdp, headers=headers) as resp:
                #check if the response is anything other than 200s
                if resp.status < 200 or resp.status >= 300:
                    error_text = await resp.text()
                    logger.error(f"WebRTC SDP exchange failed: {error_text}")
                    return web.json_response({"error": "WebRTC SDP exchange failed", "details": error_text}, status=500)
                answer_sdp = await resp.text()
                return web.json_response({'answer_sdp': answer_sdp})
    except Exception as e:
        logger.exception("Error in WebRTC SDP exchange:")
        return web.json_response({"error": str(e)}, status=500)

@routes.post('/handle-amazon-query')
async def handle_amazon_query(request):
    """
    Handles the /handle-amazon-query POST request.
    Receives a 'search_query' from the client.
    Embeds the query using Azure OpenAI.
    Performs a vector search with semantic reranking on the Azure AI Search index
    for Amazon documents.
    Returns the search results to the frontend.
    """
    try:
        # Check if initialization was successful (optional, direct search will also fail if index is not there)
        if not request.app.get('amazon_index_initialized', False):
            logger.error("Amazon Search Index was not initialized successfully. Cannot handle query.")
            return web.json_response({"error": "Amazon Search Index not available. Please check server logs."}, status=503)

        data = await request.json()
        user_query = data.get("search_query") # Corrected key from "query" to "search_query"
        if not user_query or not isinstance(user_query, str): # Added check for type
            logger.error(f"Invalid or missing 'search_query' parameter. Received: {user_query}")
            return web.json_response({"error": "'search_query' parameter is required and must be a string"}, status=400)

        logger.info(f"Handling Amazon query: '{user_query}'")

        # Initialize Azure clients - SearchClient now uses query key as index creation/population is done at startup
        search_query_credential = AzureKeyCredential(AZURE_SEARCH_API_KEY)
        search_client = SearchClient(endpoint=AZURE_SEARCH_SERVICE_ENDPOINT, index_name=AMAZON_INDEX_NAME, credential=search_query_credential)
        aoai_client = AsyncAzureOpenAI(
            api_key=AZURE_OPENAI_EMBEDDING_API_KEY,
            azure_endpoint=AZURE_OPENAI_EMBEDDING_ENDPOINT,
            api_version=AZURE_OPENAI_EMBEDDING_API_VERSION
        )

        async with search_client, aoai_client: # search_index_client removed as it's not used here anymore
            # Embed the user query
            logger.info(f"Embedding user query: '{user_query}'")
            print(f"User query: {user_query}")
            query_embedding = await get_embedding_async(user_query, aoai_client)

            # Perform vector search with semantic reranking
            logger.info(f"Performing vector search on index '{AMAZON_INDEX_NAME}'...")
            vector_query = VectorizedQuery(vector=query_embedding, k_nearest_neighbors=3, fields="embedding")

            search_results = await search_client.search(
                search_text=None, 
                vector_queries=[vector_query],
                query_type="semantic", 
                semantic_configuration_name='my-semantic-config',
                select=["id", "content", "sourcefile"], 
                top=3
            )

            results_to_return = []
            async for result in search_results:
                results_to_return.append({
                    "id": result.get("id"),
                    "content": result.get("content"),
                    "sourcefile": result.get("sourcefile"),
                    "score": result.get("@search.score"),
                    "reranker_score": result.get("@search.reranker_score")
                })
            
            logger.info(f"Found {len(results_to_return)} results for query '{user_query}'.")
            return web.json_response({"results": results_to_return})

    except Exception as e:
        logger.exception("Error handling Amazon query:")
        return web.json_response({"error": f"Failed to handle Amazon query: {str(e)}"}, status=500)

app = web.Application()
app.add_routes(routes)

# Register the startup task
app.on_startup.append(initialize_amazon_search_index)

# Add route for static files
app.router.add_static('/static', path='static')

if __name__ == '__main__':
    web.run_app(app, port=8080, host='127.0.0.1')
