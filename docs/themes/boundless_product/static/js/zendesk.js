$( document ).ready(function() {
  if (typeof(Zenbox) !== "undefined") {
    Zenbox.init({
      dropboxID:   "20307456",
      url:         "https://opengeo.zendesk.com",
      tabTooltip:  "Comments",
   /*   tabImageURL: "https://p1.zdassets.com/external/zenbox/images/tab_comments.png", */
      tabColor:    "black",
      tabPosition: "Left",
      hide_tab:    "true"
    });
  }

  $("#zenbox, a.help-contact").click(function(e){
    Zenbox.show();
    e.preventDefault();
    return false;
  });
  
  $("#zenbox-community, a.help-contact").click(function(e){
    Zenbox.show();
    e.preventDefault();
    return false;
  });
});
