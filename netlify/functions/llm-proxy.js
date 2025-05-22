// netlify/functions/llm-proxy.js
const { DEFAULT_PROMPTS } = require('./src/default_prompts');

exports.handler = async (event) => {
    try {
        // Ensure the request is a POST
        if (event.httpMethod !== 'POST') {
            return {
                statusCode: 405,
                body: JSON.stringify({ error: 'Method Not Allowed' }),
            };
        }

        // Parse the request body
        const { message, context, chatHistory } = JSON.parse(event.body);

        if (!message) {
            return {
                statusCode: 400,
                body: JSON.stringify({ error: 'Message is required' }),
            };
        }

        // Get the Anthropic API key from environment variables
        const anthropicApiKey = process.env.ANTHROPIC_API_KEY;
        if (!anthropicApiKey) {
            return {
                statusCode: 500,
                body: JSON.stringify({ error: 'Anthropic API key not configured' }),
            };
        }

        // Format chat history if available
        let formattedHistory = '';
        if (chatHistory && chatHistory.length > 0) {
            formattedHistory = chatHistory.map(msg => 
                `${msg.role === 'user' ? 'User' : 'Assistant'}: ${msg.content}`
            ).join('\n\n');
        }

        // Construct the prompt with context and history
        const userMessage = `${DEFAULT_PROMPTS.chat}\n\n${formattedHistory ? `Previous conversation:\n${formattedHistory}\n\n` : ''}${context ? `Context:\n${context}\n\n` : ''}User message: ${message}`;

        // Make the request to Anthropic's Claude API
        const response = await fetch('https://api.anthropic.com/v1/messages', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'x-api-key': anthropicApiKey,
                'anthropic-version': '2023-06-01'
            },
            body: JSON.stringify({
                model: 'claude-3-sonnet-20240229',
                max_tokens: 1024,
                messages: [
                    {
                        role: 'user',
                        content: userMessage
                    }
                ],
                system: 'You are Mana, a mystical humanoid cow AI guiding users in the realm of digital seeds. You have access to a knowledge base about MANA and TREE tokens, their ecosystems, and related information. Use this context to provide accurate and helpful responses while maintaining your mystical character.'
            }),
        });

        if (!response.ok) {
            const errorData = await response.json();
            return {
                statusCode: response.status,
                body: JSON.stringify({ error: `Anthropic API request failed: ${JSON.stringify(errorData)}` }),
            };
        }

        const data = await response.json();
        if (!data.content || !data.content[0].text) {
            return {
                statusCode: 500,
                body: JSON.stringify({ error: 'No response from Claude' }),
            };
        }

        return {
            statusCode: 200,
            body: JSON.stringify({ response: data.content[0].text }),
        };
    } catch (error) {
        console.error('Error in llm-proxy:', error);
        return {
            statusCode: 500,
            body: JSON.stringify({ error: error.message }),
        };
    }
};