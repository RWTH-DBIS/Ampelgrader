const express = require('express');
const path = require('path');
const app = express();
const port = 3000;

// Environment variables for services
const services = [
    { name: 'DBIS', url: process.env.DBIS_URL || 'http://nbblackbox-dbis.example.com' },
    { name: 'SEMWEB', url: process.env.SEMWEB_URL || 'http://nbblackbox-semweb.example.com' },
];

// Serve static files
app.use(express.static(path.join(__dirname, 'src')));

// Serve the landing page with injected services
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'src', 'landing_page.html'));
});

// Endpoint to get services
app.get('/services', (req, res) => {
    res.json(services);
});

app.listen(port, () => {
    console.log(`Server is running on http://localhost:${port}`);
});