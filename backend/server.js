const express = require('express');
const cors = require('cors');
const path = require('path');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;

console.log('SERPER_API_KEY loaded:', process.env.SERPER_API_KEY ? 'YES' : 'NO');

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.static('../frontend')); // Serve static files from current directory

// API endpoint
app.post('/api/search', async (req, res) => {
    console.log('Received search request:', req.body);
    
    const { q } = req.body;
    
    if (!q) {
        return res.status(400).json({ 
            error: true, 
            message: 'Query parameter required' 
        });
    }

    try {
        const response = await fetch('https://google.serper.dev/search', {
            method: 'POST',
            headers: {
                'X-API-KEY': process.env.SERPER_API_KEY,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ q })
        });

        const data = await response.json();
        
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