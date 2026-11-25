// Prevent double submissions: once a POST form is submitted, disable its
// submit buttons so a second click cannot send the same data again.
// The server still redirects after every successful POST.
document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || (form.method || "").toLowerCase() !== "post") return;
    if (form.dataset.submitting === "true") {
        event.preventDefault();
        return;
    }
    form.dataset.submitting = "true";
    form.querySelectorAll("button[type=submit], input[type=submit]").forEach(function (button) {
        // Disable after the browser has captured the submit, so the value is still sent.
        setTimeout(function () { button.disabled = true; }, 0);
        if (button.tagName === "BUTTON" && !button.classList.contains("nav-logout")) {
            button.dataset.label = button.textContent;
            button.textContent = "Please wait…";
        }
    });
});
// If the user navigates back to a cached page, re-enable the buttons.
window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-submitting=true]").forEach(function (form) {
        delete form.dataset.submitting;
        form.querySelectorAll("button[type=submit], input[type=submit]").forEach(function (button) {
            button.disabled = false;
            if (button.dataset.label) button.textContent = button.dataset.label;
        });
    });
});
