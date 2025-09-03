const processId = "{{id}}";
function checkGradingStatus() {
    fetch(`/grader/check_grading_status/${processId}`)
        .then(response => response.json())
        .then(data => {
            if (data.finished) {
                window.location.href = `/grader/results/${processId}`;
            } else {
                setTimeout(checkGradingStatus, 3000);
            }
        })
        .catch(() => {
            setTimeout(checkGradingStatus, 5000);
        });
}
document.addEventListener('DOMContentLoaded', checkGradingStatus);