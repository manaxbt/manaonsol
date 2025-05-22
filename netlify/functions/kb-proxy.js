const { PineconeClient } = require('@pinecone-database/pinecone');

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
        const { query, chatHistory } = JSON.parse(event.body);

        if (!query) {
            return {
                statusCode: 400,
                body: JSON.stringify({ error: 'Query is required' }),
            };
        }

        // Initialize Pinecone
        const pinecone = new PineconeClient();
        await pinecone.init({
            environment: process.env.PINECONE_ENVIRONMENT,
            apiKey: process.env.PINECONE_API_KEY,
        });

        // Combine chat history with query for better context
        const enhancedQuery = chatHistory && chatHistory.length > 0 
            ? `${chatHistory.map(msg => msg.content).join(' ')} ${query}`
            : query;

        // Get embeddings from OpenAI
        const embeddingResponse = await fetch('https://api.openai.com/v1/embeddings', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                input: enhancedQuery,
                model: "text-embedding-3-small"
            })
        });

        if (!embeddingResponse.ok) {
            throw new Error('Failed to generate embeddings');
        }

        const { data: [{ embedding }] } = await embeddingResponse.json();

        // Query Pinecone with namespaces
        const index = pinecone.Index(process.env.PINECONE_INDEX);
        
        // Query each namespace
        const namespaces = ['MANA', 'knowledge', 'backrooms'];
        const allResults = [];

        for (const namespace of namespaces) {
            const queryResponse = await index.query({
                vector: embedding,
                topK: 2,
                includeMetadata: true,
                namespace
            });

            // Add namespace to results
            queryResponse.matches.forEach(match => {
                allResults.push({
                    content: match.metadata.text,
                    score: match.score,
                    namespace,
                    metadata: match.metadata
                });
            });
        }

        // Sort by score and take top 5 overall
        const topResults = allResults
            .sort((a, b) => b.score - a.score)
            .slice(0, 5);

        return {
            statusCode: 200,
            body: JSON.stringify({
                results: topResults
            })
        };
    } catch (error) {
        console.error('Error in kb-proxy:', error);
        return {
            statusCode: 500,
            body: JSON.stringify({ error: error.message })
        };
    }
}; 