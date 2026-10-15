/* Cost display uses only provider-reported numbers; non-completed rows are separate. */
(function(root){
  "use strict";
  function known(value){ return typeof value === 'number' && Number.isFinite(value) && value >= 0; }
  function format(value){ return known(value) ? '$'+value.toFixed(6) : 'unknown cost'; }
  function formatRecord(item){
    if(item && item.status && item.status !== 'completed'){
      return {pending:'pending', generating:'generating', failed:'failed'}[item.status] || 'not completed';
    }
    return format(item && item.cost_usd);
  }
  function formatAggregate(label, aggregate){
    if(!aggregate) return label+' reported cost: unavailable';
    var completed = (aggregate.completed_known_count || 0) + (aggregate.completed_unknown_count || 0);
    var total = completed
      ? (known(aggregate.known_cost_usd) ? format(aggregate.known_cost_usd) : 'unknown')
      : 'no completed costs';
    var summary = label+' reported cost: '+total;
    if(aggregate.completed_unknown_count) summary += ' · '+aggregate.completed_unknown_count+' completed with unknown cost';
    ['failed', 'generating', 'pending', 'other'].forEach(function(status){
      var count = aggregate[status+'_count'] || 0;
      if(count) summary += ' · '+count+' '+status;
    });
    return summary;
  }
  function summarizeAggregate(summary){
    if(!summary) return 'Cost summary unavailable.';
    return formatAggregate('All-time', summary.all_time)+' | '+formatAggregate('Today (UTC)', summary.today);
  }
  var api={format:format, formatRecord:formatRecord, summarizeAggregate:summarizeAggregate};
  if(typeof module !== 'undefined' && module.exports) module.exports=api;
  else root.ImageCosts=api;
})(typeof window !== 'undefined' ? window : globalThis);
