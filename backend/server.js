const express = require('express');
const cors = require('cors');
const path = require('path');
require('dotenv').config();
const Groq = require('groq-sdk');

const groq = new Groq({ apiKey: process.env.GROQ_API_KEY });
const app = express();
const PORT = process.env.PORT || 3000;

console.log('SERPER_API_KEY loaded:', process.env.SERPER_API_KEY ? 'YES' : 'NO');

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.static('../frontend')); // Serve static files from current directory

// Query Optimization function
async function getOptimizedQuery(userQuery) {
    try {
        const completion = await groq.chat.completions.create({
            messages: [
                {
                    role: "system",
                    content: `You are a search query optimizer. 
                    Your task is to convert a user's prompt into a single, concise, high-performance Google search string.
                    
                    STRICT RULES:
                    1. Output ONLY the optimized string. 
                    2. Do NOT provide explanations, bullet points, or introductory text.
                    3. Do NOT use quotation marks around the final output.
                    4. Focus on keywords, recency (2025/2026), and intent.

                    Example Input: iphone
                    Example Output: iphone 16 pro max specs vs iphone 17 rumors 2025 2026`
                },
                {
                    role: "user",
                    content: userQuery // The variable 'q' from your request
                }
            ],
            model: "llama-3.3-70b-versatile",
            // Set temperature low for more deterministic/consistent output
            temperature: 0.1, 
            max_tokens: 50
        });

        // Use regex to clean any accidental quotes the LLM might include
        const cleanedQuery = completion.choices[0]?.message?.content?.replace(/["']/g, "").trim();
        
        return cleanedQuery || userQuery;
    } catch (error) {
        console.error("Groq Optimization Error:", error);
        return userQuery; 
    }
}

// API endpoint
app.post('/api/search', async (req, res) => {
    console.log('Received search request:', req.body);
    
    const { q } = req.body;
    
    if (!q) {
        return res.status(400).json({ 
            error:  true, 
            message: 'Query parameter required' 
        });
    }
    
    // Query optimization:
    // 1. Using LLM agent to optimize the query for better search results
    // 2. Iterate w/ diffrent system prompts to improve search relevance

    const optimizedQuery = await getOptimizedQuery(q);
    console.log('Optimized Query:', optimizedQuery);

    try {
        const response = await fetch('https://google.serper.dev/search', {
            method: 'POST',
            headers: {
                'X-API-KEY': process.env.SERPER_API_KEY,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ q: optimizedQuery })
        });

        const data = await response.json();

        // Ranking:
        // 1. Title relevance
        // 2. Google SEO ranking w/ logarithmic decay
        // Final Ranking = 0.50(title relevance) + 0.50(Google SEO ranking)



        // Normalization:
        // 1. URL canonicalization 
        // 2. Title truncation

        
        if (!response.ok) {
            throw new Error(`Serper API error: ${response.statusText}`);
        }

        console.log('Search successful');
        res.json(data);

    } catch (error) {
        console.error('Search error:', error);
        res.status(500).json({ 
            error: true, 
            message: error.message 
        });
    }
});

app.listen(PORT, () => {
    console.log(`Server running on http://localhost:${PORT}`);
    console.log(`API endpoint: http://localhost:${PORT}/api/search`);
});