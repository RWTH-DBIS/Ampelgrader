const express = require('express');
const path = require('path');
const fs = require('fs');
const { exec } = require('child_process');
const app = express();
const port = 3000;

// Serve static files
app.use(express.static(path.join(__dirname, 'src')));

// Serve the landing page with injected services
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'src', 'landing_page.html'));
});

// Endpoint to get services
app.get('/services', (req, res) => {
    exec("kubectl get ingresses -o json -A | jq '[.items[] | {host: .spec.rules[].host}]' > ./src/services.json", (error, stdout, stderr) => {
        if (error) {
            console.error(`Error executing kubectl command: ${error.message}`);
            return res.status(500).send('Error retrieving ingresses ');
        }
        if (stderr) {
            console.error(`kubectl stderr: ${stderr}`);
            return res.status(500).send('Error retrieving ingresses');
        }
        console.log(`kubectl stdout: ${stdout}`);

        // Read services from services.json
        fs.readFile(path.join(__dirname, 'src', 'services.json'), 'utf8', (err, data) => {
            if (err) {
                console.error('Error reading services.json:', err);
                return res.status(500).send('Error reading services');
            }
            const services = JSON.parse(data);
            
            res.json(services);
        });
    });
});

app.listen(port, () => {
    console.log(`Server is running on http://localhost:${port}`);
});