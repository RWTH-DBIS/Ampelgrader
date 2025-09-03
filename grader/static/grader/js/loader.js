function checkGradingStatus() {
    fetch(`/grader/check_grading_status/${window.processId}`)
        .then(response => response.json())
        .then(data => {
            if (data.finished) {
                window.location.href = `/grader/results/${window.processId}`;
            } else {
                setTimeout(checkGradingStatus, 3000);
            }
        })
        .catch(() => {
            setTimeout(checkGradingStatus, 5000);
        });
}
document.addEventListener('DOMContentLoaded', checkGradingStatus);