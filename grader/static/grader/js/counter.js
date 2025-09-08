function updateCountdown() {
    fetch(window.location.pathname)
        .then(response => response.text())
        .then(html => {
            if (document.querySelector('.counter').innerText === '00 : 00 : 00') {
                path = window.location.pathname.replace('/counter', '');
                window.location.href = path;
            } else {
                document.body.innerHTML = html;
            }
        });
}

setInterval(updateCountdown, 1000);