export async function mount(root, context) {
  const host = document.createElement('div');
  host.innerHTML = '<div class="grid cols-2"><button type="button" class="card menu-card" data-more-go="groups"><strong>分组管理</strong><span>新建、查看、重命名、合并和删除空分组</span></button><button type="button" class="card menu-card" data-more-go="account"><strong>账号与扫码</strong><span>网站账号、设备会话与 Bilibili 网页二维码登录</span></button><button type="button" class="card menu-card" data-more-go="settings"><strong>设置</strong><span>默认清晰度、目录、端口和服务器信息</span></button><button type="button" class="card menu-card" data-more-go="dashboard"><strong>概览</strong><span>作品数量、磁盘占用与运行状态</span></button></div>';
  context.commit(() => root.replaceChildren(host));
  host.addEventListener('click', event => {
    const button = event.target.closest('[data-more-go]');
    if (button) context.navigate(button.dataset.moreGo);
  }, { signal: context.signal });
  return Object.freeze({ dispose() {} });
}
