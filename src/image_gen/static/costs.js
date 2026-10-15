/* Cost display uses only provider-reported numbers; absent costs stay unknown. */
(function(root){
  "use strict";
  function known(value){ return typeof value === 'number' && Number.isFinite(value) && value >= 0; }
  function format(value){ return known(value) ? '$'+value.toFixed(6) : 'unknown cost'; }
  function summarize(items){
    var total=0, count=0;
    items.forEach(function(item){
      if(known(item.cost_usd)){ total+=item.cost_usd; count++; }
    });
    if(!items.length) return 'No generations loaded.';
    return 'Known cost in loaded history: '+(count ? format(total) : 'unknown')+
      ' · '+(items.length-count)+' with unknown cost';
  }
  var api={format:format, summarize:summarize};
  if(typeof module !== 'undefined' && module.exports) module.exports=api;
  else root.ImageCosts=api;
})(typeof window !== 'undefined' ? window : globalThis);
