/* Domain API client. Transport/auth and UI intent validation are injected by the host. */
(() => {
  'use strict';
  globalThis.YanxuEcosystemClient = Object.freeze({create({store,scope,request,captureIntent,intentValid,afterWrite,onChange,onRead}) {
    const projectPath = project => 'ecosystem?project_id='+encodeURIComponent(project);
    async function previewApply(path,body,valid) {
      if (!valid()) throw Error('项目或表单已变化，请重新查看后提交');
      // Freeze the wire payload before preview; subsequent UI changes cannot alter it.
      const payload = JSON.parse(JSON.stringify(body));
      await request(path,{...payload,dry:true});
      if (!valid()) throw Error('预览期间项目或表单已变化，本次未提交');
      return request(path,payload);
    }
    const client = {
      readProject: project => request(projectPath(project)),
      brief: (project,room) => request('ecosystem/brief?project_id='+encodeURIComponent(project)+'&room_id='+encodeURIComponent(room)),
      async spaces(mode,valid) {
        let result = await request('apps?app='+mode);
        if (!valid()) throw Error('页面已变化，请重新打开');
        if (!result.initialized) {
          await previewApply('apps',{ifRev:result.rev},valid);
          result = await request('apps?app='+mode);
        }
        return result;
      },
      registerAgent: (body,valid) => previewApply('agents/connect',body,valid),
      async refresh() {
        const ticket = store.begin(scope());
        if (!ticket) return;
        try {
          const result = await client.readProject(ticket.project);
          const changed = store.accept(ticket,scope(),result);
          if (changed === null || !store.isCurrent(ticket,scope())) return;
          onRead(result);
          if (changed) onChange();
        } catch (error) { if (store.fail(ticket,scope(),error)) onChange(); }
        finally { store.finish(ticket); }
      },
      async mutate(operation,values={}) {
        const initial = scope(), state = store.current(initial.project), intent = captureIntent();
        if (!state) throw Error('请先选择项目并读取当前记录');
        const revision = state.rev;
        const valid = () => {
          const current = scope();
          return current.project === initial.project && current.view === initial.view &&
            store.current(initial.project) === state && state.rev === revision && intentValid(intent);
        };
        const result = await previewApply('ecosystem',{...values,project_id:initial.project,operation,ifRev:revision},valid);
        if (store.value === state) state.rev = result.rev;
        store.invalidate(initial.project);
        await afterWrite();
        await client.refresh();
        return result.item;
      }
    };
    return Object.freeze(client);
  }});
})();
