document.addEventListener('DOMContentLoaded', () => {
    fetch('/services')
        .then(response => response.json())
        .then(services => {
            const serviceList = document.getElementById('service-list');
            services.forEach(service => {
                const listItem = document.createElement('li');
                const link = document.createElement('a');
                link.href = service.url;
                link.textContent = service.name;
                listItem.appendChild(link);
                serviceList.appendChild(listItem);
            });
        })
        .catch(error => console.error('Error fetching services:', error));
});