document.addEventListener("DOMContentLoaded", function() {
  var deadlineModal = document.getElementById("deadlineModal");
  if (!deadlineModal) return;
  deadlineModal.addEventListener("show.bs.modal", function(event) {
    var button = event.relatedTarget;
    if (!button) return;
    var mode = button.getAttribute("data-mode");
    var form = document.getElementById("deadlineForm");
    if (mode === "edit") {
      var id = button.getAttribute("data-id");
      var chapter = button.getAttribute("data-chapter");
      var title = button.getAttribute("data-title");
      var desc = button.getAttribute("data-desc") || "";
      var due = button.getAttribute("data-due");
      var allowLate = button.getAttribute("data-allow-late") === "true";

      document.getElementById("deadlineModalTitle").innerText = "Edit Submission Deadline";
      document.getElementById("modalChapter").value = chapter;
      document.getElementById("modalTitle").value = title;
      document.getElementById("modalDesc").value = desc;
      document.getElementById("modalDue").value = due;
      document.getElementById("modalAllowLate").checked = allowLate;
      form.action = "/coordinator/deadlines?edit_id=" + id;
    } else {
      document.getElementById("deadlineModalTitle").innerText = "Add Milestone Deadline";
      form.reset();
      form.action = "/coordinator/deadlines";
    }
  });
});
