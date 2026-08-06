// Rejection flow state — restored from localStorage on page load so the re-review
// banner in review-v2.js survives a page refresh.
(function() {
  var _BLANK = {
    hadmId: null, patName: null, rejectionReason: null,
    rejectedAt: null, rejectionLogId: null,
  };
  if (!APP.rejFlow) {
    try {
      var saved = localStorage.getItem('rejFlow_active');
      APP.rejFlow = saved ? Object.assign({}, _BLANK, JSON.parse(saved)) : Object.assign({}, _BLANK);
    } catch(e) {
      APP.rejFlow = Object.assign({}, _BLANK);
    }
  }
})();
