const CONFIG = {
    TRANSCRIPTION_MODEL: "whisper-1" 
};

/**
 * Logs a message to the on-screen log container, styled by sender.
 * @param {string} text - The message text to log.
 * @param {string} [sender='system'] - The sender of the message ('user', 'bot', or 'system').
 */
const logMessage = (text, sender = 'system') => {
    const logContainer = document.getElementById("logContainer");
    if (logContainer) {
        const messageEntryDiv = document.createElement("div");
        messageEntryDiv.classList.add('message-entry'); // For overall structure of a log/chat line

        const messageBubbleDiv = document.createElement("div");
        messageBubbleDiv.classList.add('message-bubble'); // The bubble itself

        if (sender === 'user') {
            messageBubbleDiv.classList.add('user-message');
        } else if (sender === 'bot') {
            messageBubbleDiv.classList.add('bot-message');
        } else { // 'system' or any other
            messageBubbleDiv.classList.add('system-message');
            // CSS can style .system-message differently (e.g., plain text, centered, italic)
        }

        messageBubbleDiv.textContent = text;
        messageEntryDiv.appendChild(messageBubbleDiv);
        logContainer.appendChild(messageEntryDiv);
        logContainer.scrollTop = logContainer.scrollHeight; // Auto-scroll to bottom
    } else {
        // Fallback to console if logContainer is not found
        const prefix = sender !== 'system' ? `[${sender.toUpperCase()}] ` : '';
        console.log(`${prefix}${text}`);
    }
};

let peerConnection = null;
let dataChannel = null;
let ephemeralKey = null;
let sessionId = null;

/**
 * Event listener for the 'Start Session' button.
 * Initiates a session with the backend, retrieves an ephemeral key and session ID,
 * and then starts the WebRTC connection.
 */
document.getElementById('startSessionBtn').addEventListener('click', async () => {
    const logContainer = document.getElementById("logContainer");
    if (logContainer) {
        logContainer.innerHTML = ''; // Clear previous logs
    }
    // Step 1: Start session and get ephemeral key
    try {
        const resp = await fetch('/start-session', { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) {
            logMessage('Session error: ' + (data.error || 'Unknown error'), 'system');
            return;
        }
        ephemeralKey = data.ephemeral_key;
        sessionId = data.session_id;
        // logMessage('Ephemeral Key Received (session starting).', 'system');
        // logMessage('WebRTC Session Id = ' + sessionId, 'system');
        await startWebRTC();
    } catch (error) {
        logMessage('Failed to start session: ' + error, 'system');
        console.error('Failed to start session:', error);
    }
});

/**
 * Handles the 'fetch_pdf_document' function call from the bot.
 * Fetches PDF content from the backend, processes it (truncates if necessary),
 * and sends it back to the bot via a 'response.create' event so the bot can answer the user.
 */
async function handleFetchPdfContent() {
    //logMessage('Bot requested PDF content. Fetching...', 'system');
    try {
        const resp = await fetch('/get-pdf-content', { method: 'POST' }); 
        const data = await resp.json();

        if (!resp.ok || data.error) {
            logMessage('Error fetching PDF content: ' + (data.error || 'Unknown server error'), 'system');
            const errorMessage = {
                type: "response.create",
                response: {
                    modalities: ["text", "audio"], // Ensure text is available for transcript
                    instructions: "I tried to fetch the document, but there was an error. Please try again or ask something else.",
                    max_output_tokens: 100
                }
            };
            if (dataChannel && dataChannel.readyState === 'open') dataChannel.send(JSON.stringify(errorMessage));
            return;
        }

        if (data.pdf_text) {
            //logMessage(`PDF content fetched (length: ${data.pdf_text.length}). Preparing for bot.`, 'system');
            
            const MAX_INLINE_PDF_LENGTH = 3000; 
            let pdfContentForBot = data.pdf_text;
            let instructionText = "";

            if (data.pdf_text.length > MAX_INLINE_PDF_LENGTH) {
                pdfContentForBot = data.pdf_text.substring(0, MAX_INLINE_PDF_LENGTH) + "\\n... (Content truncated due to length)";
                //logMessage(`PDF content is long, truncating for bot instruction.`, 'system');
                instructionText = `I have successfully fetched the financial document. It is quite extensive. Here is the initial portion of the content: \"\"\"${pdfContentForBot}\"\"\" Please use this information to answer the user\'s current question about the financials. If this initial part is insufficient, you might need to guide the user to ask a more specific question.`;
            } else {
                logMessage(`PDF content length is within limits. Using full text for bot instruction.`, 'system');
                instructionText = `I have successfully fetched the financial document. The content is as follows: \"\"\"${pdfContentForBot}\"\"\" Please use this information to answer the user\'s current question about the financials. You can refer to this content for subsequent related questions in this session.`;
            }

            const pdfResponseMessage = {
                type: "response.create",
                response: {
                    modalities: ["text", "audio"], // Ensure text is available for transcript
                    instructions: instructionText,
                    max_output_tokens: 500 
                }
            };
            if (dataChannel && dataChannel.readyState === 'open') dataChannel.send(JSON.stringify(pdfResponseMessage));
            //logMessage('Sent response.create to bot with PDF context.', 'system');

        } else {
            logMessage('No text found in PDF or PDF was empty.', 'system');
             const noTextMessage = {
                type: "response.create",
                response: {
                    modalities: ["text", "audio"], // Ensure text is available for transcript
                    instructions: "I fetched the document, but it appears to be empty or no text could be extracted. I cannot answer questions based on it.",
                    max_output_tokens: 100
                }
            };
            if (dataChannel && dataChannel.readyState === 'open') dataChannel.send(JSON.stringify(noTextMessage));
        }
    } catch (error) {
        logMessage('Exception while fetching PDF content: ' + error, 'system');
         const exceptionMessage = {
            type: "response.create",
            response: {
                modalities: ["text", "audio"], // Ensure text is available for transcript
                instructions: "I encountered an unexpected issue while trying to access the document. Please try again.",
                max_output_tokens: 100
            }
        };
        if (dataChannel && dataChannel.readyState === 'open') dataChannel.send(JSON.stringify(exceptionMessage));
    }
}

/**
 * Initializes and manages the WebRTC connection.
 * Sets up the peer connection, media streams, data channel, and event listeners for data channel messages.
 * Also handles the SDP offer/answer exchange with the backend.
 */
async function startWebRTC() {
    peerConnection = new RTCPeerConnection();
    const audioElement = document.createElement('audio');
    audioElement.autoplay = true;
    // document.body.appendChild(audioElement); // No longer appending to body directly, assuming UI has an audio element or it's not visible
    //logMessage('WebRTC Peer Connection Created', 'system');
    
    peerConnection.ontrack = (event) => {
        if (audioElement.srcObject !== event.streams[0]) {
            audioElement.srcObject = event.streams[0];
            //logMessage('Audio track received and attached.', 'system');
        }
    };

    try {
        const clientMedia = await navigator.mediaDevices.getUserMedia({ audio: true });
        clientMedia.getTracks().forEach(track => peerConnection.addTrack(track, clientMedia));
        //logMessage('Microphone access granted and audio track added.', 'system');
    } catch (err) {
        logMessage('Error accessing microphone: ' + err.message, 'system');
        console.error('Error accessing microphone:', err);
        return; 
    }
    
    dataChannel = peerConnection.createDataChannel('realtime-channel');
    //logMessage('Data channel created', 'system');
    
    dataChannel.addEventListener('open', () => {
        //logMessage('Data channel is open', 'system');
        updateSession(); 

        if (dataChannel && dataChannel.readyState === 'open') {
            const greetingMessage = {
                type: "response.create",
                response: {
                    modalities: ["text", "audio"], // Ensure text is available for transcript
                    instructions: "Hello. I am here to assist you on anything related to apple and Amazon finances",
                    max_output_tokens: 100 
                }
            };
            //logMessage("Client instructing bot to greet with: \\\"" + greetingMessage.response.instructions + "\\\"", 'system');
            dataChannel.send(JSON.stringify(greetingMessage));
        }
    });

    dataChannel.addEventListener('message', (event) => {
        const realtimeEvent = JSON.parse(event.data);
        // Log the raw event for debugging - can be re-enabled if needed.
        //logMessage(`Received event from bot: ${event.data}`, 'system');

        // Display messages in the transcript ONLY from "response.audio_transcript.done" events (BOT'S SPEECH)
        if (realtimeEvent.type === "response.audio_transcript.done" && realtimeEvent.transcript) {
            logMessage(realtimeEvent.transcript, 'bot');
        }
        // Display user's transcribed speech
        else if (realtimeEvent.type === "conversation.item.input_audio_transcription.completed" && realtimeEvent.transcript) {
            logMessage(realtimeEvent.transcript, 'user');
        }
        // Handler for session updates
        else if (realtimeEvent.type === "session.update") {
            // This is typically system info, not direct bot speech to display in a chat bubble.
            const instructionsPreview = realtimeEvent.session && realtimeEvent.session.instructions 
                ? realtimeEvent.session.instructions.substring(0, 100) + "..." 
                : "N/A";
            logMessage("Bot session updated. Current instructions (preview): " + instructionsPreview, 'system');
        } else if (realtimeEvent.type === "session.error") {
            logMessage("Bot session error: " + (realtimeEvent.error && realtimeEvent.error.message ? realtimeEvent.error.message : "Unknown error"), 'system');
        } else if (realtimeEvent.type === "session.end") {
            logMessage("Bot session ended.", 'system');
            stopSession(); 
        } else if (realtimeEvent.type === "response.function_call_arguments.done") {
            //logMessage(`Bot calling function: ${realtimeEvent.name} with args: ${realtimeEvent.arguments}`, 'system');
            
            if (realtimeEvent.name === "fetch_pdf_document") {
                handleFetchPdfContent();
            } else if (realtimeEvent.name === "handle_amazon_query_tool") {
                try {
                    const parsedArgs = JSON.parse(realtimeEvent.arguments);
                    const actualQueryString = parsedArgs.search_query;

                    if (actualQueryString && typeof actualQueryString === 'string') {
                        handleAmazonQueryRequest(realtimeEvent.id, actualQueryString);
                    } else {
                        logMessage("Error: 'search_query' not found or invalid in parsed arguments for handle_amazon_query_tool.", 'system');
                        const correctedErrorResponse = {
                            type: "response.create",
                            response: {
                                modalities: ["text", "audio"],
                                instructions: "I tried to process the Amazon query, but the search query was missing or invalid. Please try rephrasing your request.",
                                max_output_tokens: 100
                            }
                        };
                        if (dataChannel && dataChannel.readyState === 'open') dataChannel.send(JSON.stringify(correctedErrorResponse));
                    }
                } catch (e) {
                    logMessage("Error parsing arguments for handle_amazon_query_tool: " + e, 'system');
                    const errorResponse = { 
                        type: "response.create",
                        response: {
                            modalities: ["text", "audio"],
                            instructions: "I encountered an issue parsing the arguments for the Amazon query. Please try again.",
                            max_output_tokens: 100
                        }
                    };
                    if (dataChannel && dataChannel.readyState === 'open') dataChannel.send(JSON.stringify(errorResponse));
                }
            } else {
                logMessage("Bot tried to call an unknown function: " + realtimeEvent.name, 'system');
                 const unknownFunctionResponse = {
                    type: "response.create",
                    response: {
                        modalities: ["text", "audio"],
                        instructions: `I tried to call a function named \'${realtimeEvent.name}\', but I don\'t know how to do that. Can you try a different request?`,
                        max_output_tokens: 100
                    }
                };
                if (dataChannel && dataChannel.readyState === 'open') dataChannel.send(JSON.stringify(unknownFunctionResponse));
            }
        }
        // Not adding a generic 'else' here to avoid double-logging, as the raw event is already logged at the start.
        // Specific unhandled event types can be logged if necessary by adding more 'else if' blocks.
    });
    dataChannel.addEventListener('close', () => {
        //logMessage('Data channel is closed', 'system');
    });
    dataChannel.addEventListener('error', (error) => {
        logMessage('Data channel error: ' + error, 'system');
        console.error('Data channel error:', error);
    });

    peerConnection.onicecandidate = async (event) => {
        if (event.candidate) {
            // logMessage('ICE candidate: (details omitted)', 'system'); // Usually too verbose for chat log
        }
    };

    peerConnection.oniceconnectionstatechange = () => {
        if (peerConnection) {
            //logMessage('ICE connection state change: ' + peerConnection.iceConnectionState, 'system');
            if (peerConnection.iceConnectionState === 'failed' || 
                peerConnection.iceConnectionState === 'disconnected' || 
                peerConnection.iceConnectionState === 'closed') {
                logMessage('WebRTC connection lost or failed.', 'system');
            }
        }
    };
    
    //logMessage('Creating SDP offer...', 'system');
    const offer = await peerConnection.createOffer();
    await peerConnection.setLocalDescription(offer);
    
    try {
        const sdpResp = await fetch('/webrtc-sdp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ephemeral_key: ephemeralKey, offer_sdp: offer.sdp })
        });
        const sdpData = await sdpResp.json();
        if (!sdpResp.ok) {
            logMessage('SDP error: ' + (sdpData.error || 'Unknown error') + ' Status: ' + sdpResp.status, 'system');
            return;
        }
        //logMessage('SDP answer received, setting remote description.', 'system');
        await peerConnection.setRemoteDescription({ type: 'answer', sdp: sdpData.answer_sdp });
        //logMessage('Remote description set. WebRTC connection should be establishing.', 'system');

        if (!document.getElementById('closeSessionBtn')) {
            const button = document.createElement('button');
            button.id = 'closeSessionBtn';
            button.innerText = 'Close Session';
            button.onclick = stopSession;
            // Append to a specific part of the body, e.g., after the start button or log container
            const startButton = document.getElementById('startSessionBtn');
            if (startButton && startButton.parentNode) {
                startButton.parentNode.insertBefore(button, startButton.nextSibling);
            } else {
                document.body.appendChild(button);
            }
        }

    } catch (error) {
        logMessage('Error during SDP exchange: ' + error, 'system');
        console.error('Error during SDP exchange:', error);
    }
}

/**
 * Sends a 'session.update' event to the bot.
 * This configures the bot's instructions, persona, and available tools (functions).
 * It's called when the data channel opens.
 * Configuration for instructions, tools, turn_detection, and tool_choice is fetched from the backend.
 */
async function updateSession() {
    //logMessage('Updating session with bot instructions and tools...', 'system');
    if (!dataChannel || dataChannel.readyState !== 'open') {
        logMessage('Cannot update session: Data channel not open.', 'system');
        return;
    }

    try {
        // Fetch session configuration (instructions, tools, etc.) from the backend
        const response = await fetch('/get-session-configuration'); 
        if (!response.ok) {
            logMessage(`Error fetching session configuration: ${response.statusText} (${response.status})`, 'system');
            console.error('Error fetching session configuration:', response);
            // Consider sending a default or error state to the bot, or simply returning
            return;
        }
        const configFromServer = await response.json();

        const event = {
            type: "session.update",
            session: {
                instructions: configFromServer.instructions,
                input_audio_transcription: {
                    model: configFromServer.transcription_model // Updated to use model from server config
                },
                turn_detection: configFromServer.turn_detection,
                tools: configFromServer.tools,
                tool_choice: configFromServer.tool_choice || "auto" // Fallback to "auto" if not provided
            }
        };
        
        //logMessage("Sending session.update to bot (details in console).", 'system');
        console.log("Sending session.update with fetched configuration: " + JSON.stringify(event, null, 2)); 
        dataChannel.send(JSON.stringify(event));

    } catch (error) {
        logMessage('Failed to update session with server configuration: ' + error, 'system');
        console.error('Failed to update session with server configuration:', error);
    }
}

/**
 * Closes the WebRTC data channel and peer connection.
 */
function stopSession() {
    //logMessage("Closing session...", 'system');
    if (dataChannel) {
        dataChannel.close();
        dataChannel = null; // Clear reference
    }
    if (peerConnection) {
        peerConnection.close();
        peerConnection = null; // Clear reference
    }
    ephemeralKey = null;
    sessionId = null;
    logMessage("Session closed.", 'system');
    const closeButton = document.getElementById('closeSessionBtn');
    if (closeButton) {
        closeButton.remove();
    }
    const startButton = document.getElementById('startSessionBtn');
    if (startButton) {
        startButton.disabled = false; // Re-enable if it was disabled during session
    }
}

/**
 * Handles the 'handle_amazon_query_tool' function call from the bot.
 * @param {string} toolCallId - The ID of the tool call event from the bot.
 * @param {string} searchQueryString - The search query string provided by the bot.
 * Fetches search results for the Amazon query from the backend, summarizes them,
 * and sends them back to the bot via a 'response.create' event for the bot to answer the user.
 */
async function handleAmazonQueryRequest(toolCallId, query) {
    //logMessage(\`Bot requested Amazon query: \"\${query}\". Fetching...\`, 'system');
    try {
        const resp = await fetch('/handle-amazon-query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ search_query: query })
        });
        const data = await resp.json();

        if (!resp.ok || data.error) {
            logMessage('Error performing Amazon query: ' + (data.error || 'Unknown server error'), 'system');
            const errorMessage = {
                type: "response.create",
                response: {
                    modalities: ["text", "audio"], // Ensure text is available for transcript
                    instructions: "I tried to search for Amazon information, but there was an error. Please try again.",
                    max_output_tokens: 100
                }
            };
            if (dataChannel && dataChannel.readyState === 'open') dataChannel.send(JSON.stringify(errorMessage));
            return;
        }

        if (data.summary) {
            //logMessage(\`Amazon query summary received (length: \${data.summary.length}). Preparing for bot.\`, 'system');
            
            const instructionText = `I have found information related to your Amazon query. Here is a summary: \"\"\"\${data.summary}\"\"\" Please use this to answer the user.`;
            
            const amazonResponseMessage = {
                type: "response.create",
                response: {
                    modalities: ["text", "audio"], // Ensure text is available for transcript
                    instructions: instructionText,
                    max_output_tokens: 500 
                }
            };
            if (dataChannel && dataChannel.readyState === 'open') dataChannel.send(JSON.stringify(amazonResponseMessage));
            //logMessage('Sent response.create to bot with Amazon query summary.', 'system');

        } else {
            logMessage('No summary received for Amazon query.', 'system');
            const noSummaryMessage = {
                type: "response.create",
                response: {
                    modalities: ["text", "audio"], // Ensure text is available for transcript
                    instructions: "I searched for the Amazon information, but I couldn't find a specific summary. You might want to try a different query.",
                    max_output_tokens: 100
                }
            };
            if (dataChannel && dataChannel.readyState === 'open') dataChannel.send(JSON.stringify(noSummaryMessage));
        }
    } catch (error) {
        logMessage('Exception during Amazon query: ' + error, 'system');
        const exceptionMessage = {
            type: "response.create",
            response: {
                modalities: ["text", "audio"], // Ensure text is available for transcript
                instructions: "I encountered an unexpected issue while trying to get Amazon information. Please try again.",
                max_output_tokens: 100
            }
        };
        if (dataChannel && dataChannel.readyState === 'open') dataChannel.send(JSON.stringify(exceptionMessage));
    }
}

// Ensure the DOM is fully loaded before trying to access elements,
// especially if the script is in the <head> without 'defer'.
// If script is at the end of <body> or has 'defer', this is less critical
// but good practice for robustness.
document.addEventListener('DOMContentLoaded', () => {
    // Any setup that requires the DOM to be ready can go here.
    // For example, if the 'startSessionBtn' was not found initially,
    // this would be a place to re-check or log an error.
    if (!document.getElementById('startSessionBtn')) {
        console.error("Start Session Button not found on DOMContentLoaded!");
        logMessage("Error: UI elements not found. The page might not work correctly.");
    }
});
