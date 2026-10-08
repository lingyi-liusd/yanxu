/* Project-scoped read state. No DOM, network, credentials or model invocation. */
(() => {
  'use strict';
  const sameScope = (a,b) => a.project === b.project && a.view === b.view;
  globalThis.YanxuEcosystemState = Object.freeze({create() {
    let pending = null, sequence = 0;
    return {
      value:null, error:'',
      current(project) { return this.value?.project_id === project ? this.value : null; },
      begin(scope) {
        if (!scope.active || !scope.project || (pending && sameScope(pending,scope))) return null;
        pending = {...scope,sequence:++sequence};
        return pending;
      },
      isCurrent(ticket,scope) { return pending === ticket && scope.active && sameScope(ticket,scope); },
      accept(ticket,scope,result) {
        if (!this.isCurrent(ticket,scope)) return null;
        if (result.project_id !== ticket.project) throw Error('返回的项目与当前请求不符，请重新读取');
        if (this.value?.project_id === result.project_id && Number.isInteger(this.value.rev) && Number.isInteger(result.rev) && result.rev < this.value.rev) return null;
        const changed = !this.value || JSON.stringify(this.value) !== JSON.stringify(result) || !!this.error;
        if (changed) this.value = result;
        this.error = '';
        return changed;
      },
      fail(ticket,scope,error) {
        if (!this.isCurrent(ticket,scope)) return false;
        this.error = error.message;
        return true;
      },
      finish(ticket) { if (pending === ticket) pending = null; },
      invalidate(project) { if (pending?.project === project) pending = null; }
    };
  }});
})();
