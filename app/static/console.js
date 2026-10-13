"use strict";
const $ = (selector, root = document) => root.querySelector(selector);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const id = encodeURIComponent;
let apiKey = "demo-commerce-key", connected = false, selectedScenario = 2;
let sourceGeneration = 0, threadGeneration = 0, currentInquiry = null;
let inquiryOffset = 0, messageOffset = 0;
const pendingCommands = new Map();
const scenarioLabels = ["付款后待打包", "运输中", "已签收", "多包裹 / 部分发货", "等待补货", "已打包 / 待揽收", "物流长时间未更新", "物流接口超时", "仓库接口不可用", "物流记录缺失", "仓库与物流冲突", "订单不存在"];
const faultModes = {
  NORMAL: "正常响应，覆盖场景原有故障。", TIMEOUT_ONCE: "下一次物流 / 仓库读取超时；之后恢复。物流状态与事件共享次数。",
  ALWAYS_TIMEOUT: "持续返回 HTTP 504。", HTTP_500: "来源返回 HTTP 500。", HTTP_429: "来源返回 HTTP 429 限流。",
  SLOW_RESPONSE: "延迟后响应；输入 1–10000 毫秒。", STALE_DATA: "返回旧的来源时间。", EMPTY_RESULT: "返回来源定义的空结果。",
  PARTIAL_FAILURE: "此来源记录返回 HTTP 503，其他记录与系统保持独立。", CONFLICTING_DATA: "返回互相冲突的来源事实。", MALFORMED_RESPONSE: "返回 HTTP 200，但响应不是有效 JSON。"
};
function notice(text = "") { $("#notice").textContent = text; $("#notice").hidden = !text; }
function errorText(error) { return `${error.status ? `HTTP ${error.status} · ` : ""}${error.message}${error.requestId ? ` · 请求 ${error.requestId}` : ""}`; }
function syncSendButton() { $("#send-button").disabled = !connected || !currentInquiry || Boolean($("#send-message").dataset.busy); }
async function api(path, method = "GET", body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const headers = {"X-API-Key": apiKey};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetch(path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal});
    const raw = await response.text();
    let data;
    try { data = raw ? JSON.parse(raw) : null; }
    catch { throw Object.assign(new Error("来源返回无法解析的 JSON"), {status: response.status, requestId: response.headers.get("X-Request-Id")}); }
    if (!response.ok) throw Object.assign(new Error(data?.error?.message || response.statusText), {status: response.status, requestId: data?.error?.request_id, code: data?.error?.code});
    return {data, status: response.status};
  } catch (error) {
    if (error.name === "AbortError") throw new Error("请求超过 20 秒。写入可能已被接收，请先检查来源状态。");
    throw error;
  } finally { clearTimeout(timeout); }
}
function jsonView(target, data) { target.replaceChildren(node("pre", JSON.stringify(data, null, 2))); }
function view(name) {
  document.querySelectorAll(".view").forEach(el => { el.hidden = el.id !== `view-${name}`; });
  document.querySelectorAll(".nav").forEach(el => {
    el.classList.toggle("active", el.dataset.view === name);
    el.setAttribute("aria-pressed", String(el.dataset.view === name));
  });
  $("#page-title").textContent = {sources: "场景与源数据", support: "客户会话", faults: "故障控制", simulation: "模拟数据推进"}[name];
  if (connected && name === "support") loadInquiries();
  if (connected && name === "faults") loadFaults();
  window.scrollTo({top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
}
document.querySelectorAll(".nav").forEach(button => button.addEventListener("click", () => view(button.dataset.view)));
async function runForm(form, action) {
  const buttons = [...form.querySelectorAll("button")];
  if (form.dataset.busy) return;
  form.dataset.busy = "true";
  buttons.forEach(button => { button.disabled = true; });
  const output = $(".operation-result", form);
  if (output) { output.className = "operation-result"; output.textContent = "请求处理中…"; }
  try {
    await action();
  } catch (error) {
    if (output) { output.textContent = errorText(error); output.className = "operation-result error"; }
    else notice(errorText(error));
  } finally {
    delete form.dataset.busy;
    buttons.forEach(button => { button.disabled = false; });
    syncSendButton();
  }
}
function success(form, text) { const el = $(".operation-result", form); if (el) { el.textContent = text; el.className = "operation-result success"; } }
async function command(scope, path, payload) {
  const signature = JSON.stringify([path, payload]);
  let pending = pendingCommands.get(scope);
  if (!pending || pending.signature !== signature) {
    pending = {signature, key: crypto.randomUUID()};
    pendingCommands.set(scope, pending);
  }
  let result;
  try { result = await api(path, "POST", {...payload, idempotency_key: pending.key}); }
  catch (error) {
    if (!error.status) error.message += " 同一页面重试相同会话请求会沿用幂等键。";
    throw error;
  }
  pendingCommands.delete(scope);
  return result;
}
async function refreshSummary() {
  const {data} = await api("/api/admin/summary");
  $("#metrics").replaceChildren();
  [["OMS 订单", data.orders], ["包裹", data.parcels], ["客户询问", data.inquiries], ["已发送模拟回复", data.replies]].forEach(([label, value]) => {
    const card = node("div", undefined, "metric"); card.append(node("span", label), node("strong", String(value))); $("#metrics").append(card);
  });
  $("#metrics").title = `来源基准时间：${data.base_time}`;
  $("#base-time").textContent = `来源基准时间 ${data.base_time} · ${data.seed_version} · 显式故障覆盖 ${data.fault_overrides}`;
}
async function refreshAfterWrite() {
  try { await refreshSummary(); }
  catch (error) { notice(`写入已接受，但统计刷新失败：${errorText(error)}`); }
}
async function connect() {
  notice(); apiKey = $("#api-key").value; connected = false; syncSendButton();
  $("#connection").textContent = "连接中…"; $("#connection").dataset.state = "pending";
  try {
    await refreshSummary(); connected = true;
    $("#connection").textContent = "● 已连接";
    $("#connection").dataset.state = "connected";
    await Promise.all([inspect(), loadPolicy(), loadFaults(), loadInquiries()]);
    if (currentInquiry) await openInquiry(currentInquiry.inquiry_id);
    if ($("#customer-orders").childElementCount) await loadCustomerOrders();
  } catch (error) {
    connected = false; $("#connection").textContent = "连接失败"; notice(errorText(error));
    $("#connection").dataset.state = "error";
  }
  syncSendButton();
}
$("#connect-form").addEventListener("submit", event => { event.preventDefault(); runForm(event.currentTarget, connect); });
scenarioLabels.forEach((label, index) => {
  const number = index + 1;
  const button = node("button", undefined, "scenario");
  button.append(node("strong", `S${String(number).padStart(2, "0")}`), node("span", label));
  button.classList.toggle("selected", number === selectedScenario);
  button.addEventListener("click", () => {
    selectedScenario = number;
    $("#order-id").value = `ORD-DEMO-${String(number).padStart(3, "0")}`;
    document.querySelectorAll(".scenario").forEach((el, n) => el.classList.toggle("selected", n === index));
    inspect();
  });
  $("#scenarios").append(button);
});
function sourceCard(title, path, generation, onRetry, group = "") {
  const card = node("article", undefined, `panel source-card ${group}`);
  const header = node("header"), status = node("span", "请求中", "status pending"), retry = node("button", "重试", "secondary");
  header.append(node("h3", title), status, retry);
  const content = node("div", "等待来源响应…", "muted");
  card.append(header, node("div", path, "muted"), content);
  $("#source-results").append(card);
  const load = async () => {
    retry.disabled = true; status.textContent = "请求中"; status.className = "status pending";
    try {
      const result = await api(path);
      if (generation !== sourceGeneration) return null;
      status.textContent = `HTTP ${result.status}`; status.className = "status"; jsonView(content, result.data);
      return result.data;
    } catch (error) {
      if (generation !== sourceGeneration) return null;
      status.textContent = error.status ? `HTTP ${error.status}` : "连接失败"; status.className = "status bad";
      content.replaceChildren(node("p", errorText(error)));
      return null;
    } finally { retry.disabled = false; }
  };
  retry.addEventListener("click", async () => {
    const data = await load();
    if (onRetry && generation === sourceGeneration) onRetry(data);
  });
  return load();
}
async function inspect() {
  const order = $("#order-id").value.trim(); if (!order) return;
  const match = /^ORD-DEMO-(00[1-9]|01[0-2])$/.exec(order);
  selectedScenario = match ? Number(match[1]) : null;
  document.querySelectorAll(".scenario").forEach((button, index) => button.classList.toggle("selected", index + 1 === selectedScenario));
  const generation = ++sourceGeneration;
  $("#source-results").replaceChildren();
  sourceCard("OMS · 订单", `/api/oms/orders/${id(order)}`, generation);
  sourceCard("Warehouse · 原始备注", `/api/warehouse/orders/${id(order)}/notes`, generation);
  const parcels = await sourceCard("OMS · 包裹引用", `/api/oms/orders/${id(order)}/parcels`, generation, data => renderParcels(data, generation));
  renderParcels(parcels, generation);
}
function renderParcels(parcels, generation) {
  if (generation !== sourceGeneration) return;
  document.querySelectorAll("#source-results .logistics-card").forEach(card => card.remove());
  if (!Array.isArray(parcels)) return;
  for (const parcel of parcels) {
    if (!parcel.tracking_number) {
      const card = node("article", undefined, "panel source-card logistics-card");
      card.append(node("h3", `Logistics · ${parcel.parcel_id}`), node("p", "OMS 运单号为 null，无法请求物流来源。")); $("#source-results").append(card);
      continue;
    }
    sourceCard(`Logistics · ${parcel.tracking_number}`, `/api/logistics/shipments/${id(parcel.tracking_number)}`, generation, null, "logistics-card");
    sourceCard(`Events · ${parcel.tracking_number}`, `/api/logistics/shipments/${id(parcel.tracking_number)}/events`, generation, null, "logistics-card");
  }
}
$("#inspect-form").addEventListener("submit", event => { event.preventDefault(); inspect(); });
let customerOffset = 0, customerGeneration = 0;
async function loadCustomerOrders() {
  const generation = ++customerGeneration, customer = $("#customer-id").value.trim();
  if (!customer) return;
  $("#prev-orders").disabled = true; $("#next-orders").disabled = true;
  try {
    const {data} = await api(`/api/oms/customers/${id(customer)}/orders?limit=10&offset=${customerOffset}`);
    if (generation !== customerGeneration) return;
    $("#customer-orders").replaceChildren();
    if (!data.length) $("#customer-orders").append(node("p", "没有订单。"));
    data.forEach(order => {
      const button = node("button", `${order.order_id} · ${order.status}`, "secondary");
      button.addEventListener("click", () => { $("#order-id").value = order.order_id; inspect(); });
      $("#customer-orders").append(button);
    });
    $("#orders-page").textContent = `第 ${customerOffset / 10 + 1} 页`;
    $("#prev-orders").disabled = customerOffset === 0; $("#next-orders").disabled = data.length < 10;
  } catch (error) {
    if (generation !== customerGeneration) return;
    $("#customer-orders").textContent = errorText(error); $("#orders-page").textContent = "读取失败";
  }
}
$("#customer-form").addEventListener("submit", event => { event.preventDefault(); customerOffset = 0; loadCustomerOrders(); });
$("#prev-orders").addEventListener("click", () => { customerOffset = Math.max(0, customerOffset - 10); loadCustomerOrders(); });
$("#next-orders").addEventListener("click", () => { customerOffset += 10; loadCustomerOrders(); });
$("#open-scenario-inquiry").addEventListener("click", () => {
  const match = /^ORD-DEMO-(00[1-9]|01[0-2])$/.exec($("#order-id").value.trim());
  if (!match) { notice("只有 S01–S12 有稳定的场景会话；其他订单可在客户会话中筛选。"); return; }
  view("support"); openInquiry(`INQ-DEMO-${match[1]}`);
});
async function loadPolicy() { try { jsonView($("#policy-result"), (await api("/api/policy/order-support")).data); } catch (error) { $("#policy-result").textContent = errorText(error); } }
let listGeneration = 0;
async function loadInquiries() {
  const generation = ++listGeneration;
  $("#prev-inquiries").disabled = true; $("#next-inquiries").disabled = true;
  const params = new URLSearchParams({limit: "10", offset: String(inquiryOffset)});
  if ($("#inquiry-status").value) params.set("status", $("#inquiry-status").value);
  if ($("#inquiry-order").value.trim()) params.set("order_id", $("#inquiry-order").value.trim());
  try {
    const {data} = await api(`/api/support/inquiries?${params}`);
    if (generation !== listGeneration) return;
    $("#inquiries").replaceChildren();
    if (!data.length) $("#inquiries").append(node("p", "没有符合条件的会话。"));
    data.forEach(inquiry => {
      const button = node("button", undefined, "inquiry");
      button.classList.toggle("active", currentInquiry?.inquiry_id === inquiry.inquiry_id);
      button.append(node("strong", `${inquiry.inquiry_id} · ${inquiry.status}`), node("span", inquiry.order_id || "未关联订单"), node("span", inquiry.customer_message, "preview"));
      button.addEventListener("click", () => openInquiry(inquiry.inquiry_id)); $("#inquiries").append(button);
    });
    $("#inquiry-page").textContent = `第 ${inquiryOffset / 10 + 1} 页`;
    $("#prev-inquiries").disabled = inquiryOffset === 0; $("#next-inquiries").disabled = data.length < 10;
  } catch (error) {
    if (generation !== listGeneration) return;
    $("#inquiries").replaceChildren(node("p", errorText(error))); $("#inquiry-page").textContent = "读取失败";
  }
}
$("#inquiry-filter").addEventListener("submit", event => { event.preventDefault(); inquiryOffset = 0; loadInquiries(); });
$("#prev-inquiries").addEventListener("click", () => { inquiryOffset = Math.max(0, inquiryOffset - 10); loadInquiries(); });
$("#next-inquiries").addEventListener("click", () => { inquiryOffset += 10; loadInquiries(); });
async function openInquiry(inquiryId) {
  if (currentInquiry?.inquiry_id !== inquiryId) {
    $("#send-message").reset(); $("#followup-reference").hidden = true;
    $("#send-message .operation-result").textContent = "";
  }
  const generation = ++threadGeneration;
  currentInquiry = null; $("#send-button").disabled = true;
  $("#latest-customer").hidden = true;
  $("#inquiry-id").value = inquiryId; $("#messages").replaceChildren(); $("#more-messages").hidden = true;
  $("#thread-info").textContent = "读取会话中…"; messageOffset = 0;
  try {
    const {data} = await api(`/api/support/inquiries/${id(inquiryId)}`);
    if (generation !== threadGeneration) return;
    currentInquiry = data; syncSendButton();
    $("#thread-info").textContent = `${data.status} · ${data.order_id || "无订单关联"} · 来源更新时间 ${data.updated_at ?? "null"}`;
    $("#latest-customer").replaceChildren(node("strong", "当前最新客户消息"), node("small", data.latest_customer_message_id ?? "null"), node("div", data.customer_message, "body"));
    $("#latest-customer").hidden = false;
    await loadMessages(generation); loadInquiries();
  } catch (error) { if (generation === threadGeneration) $("#thread-info").textContent = errorText(error); }
}
async function loadMessages(generation = threadGeneration) {
  if (!currentInquiry) return;
  const inquiryId = currentInquiry.inquiry_id;
  try {
    const {data} = await api(`/api/support/inquiries/${id(inquiryId)}/messages?limit=50&offset=${messageOffset}`);
    if (generation !== threadGeneration) return;
    data.forEach(message => {
      const card = node("article", undefined, `message ${message.sender_type === "SUPPORT" ? "support" : "customer"}`);
      card.append(node("strong", message.sender_type === "SUPPORT" ? "模拟客服回复" : "客户消息"), node("small", `${message.created_at} · ${message.message_id}`), node("div", message.text, "body"));
      if (message.in_reply_to_message_id) card.append(node("small", `回复绑定：${message.in_reply_to_message_id}`));
      $("#messages").append(card);
    });
    messageOffset += data.length; $("#more-messages").hidden = data.length < 50;
    $("#more-messages").textContent = "加载后续消息";
    if (!messageOffset) $("#messages").append(node("p", "暂无消息记录。"));
  } catch (error) { notice(errorText(error)); }
}
$("#more-messages").addEventListener("click", async () => {
  const button = $("#more-messages");
  if (button.disabled) return;
  button.disabled = true;
  try { await loadMessages(); }
  finally { button.disabled = false; }
});
$("#open-inquiry").addEventListener("submit", event => { event.preventDefault(); openInquiry($("#inquiry-id").value.trim()); });
$("#new-inquiry").addEventListener("submit", event => {
  event.preventDefault(); const form = event.currentTarget;
  runForm(form, async () => {
    const payload = {customer_message: form.elements.text.value, order_id: form.elements.order_id.value.trim() || null};
    const {data} = await command("new", "/api/support/inquiries", payload);
    success(form, `已接收 ${data.inquiry_id}`); form.reset(); inquiryOffset = 0;
    await openInquiry(data.inquiry_id); await refreshAfterWrite();
  });
});
$("#send-message select[name=kind]").addEventListener("change", event => { $("#followup-reference").hidden = event.target.value !== "followup"; });
$("#send-message").addEventListener("submit", event => {
  event.preventDefault(); const form = event.currentTarget;
  runForm(form, async () => {
    if (!currentInquiry) throw new Error("请先打开会话。");
    const inquiry = currentInquiry, followup = form.elements.kind.value === "followup";
    const payload = {text: form.elements.text.value};
    if (followup) {
      if (form.elements.reference.value === "clear") payload.order_id = null;
      if (form.elements.reference.value === "set") { payload.order_id = form.elements.order_id.value.trim(); if (!payload.order_id) throw new Error("请输入新的订单 ID。"); }
    } else payload.in_reply_to_message_id = inquiry.latest_customer_message_id;
    try {
      const {data} = await command(`thread-${inquiry.inquiry_id}`, `/api/support/inquiries/${id(inquiry.inquiry_id)}/${followup ? "messages" : "replies"}`, payload);
      success(form, `已接收 ${data.message_id || data.reply_id}`); form.elements.text.value = "";
      await openInquiry(inquiry.inquiry_id); await refreshAfterWrite();
    } catch (error) {
      if (error.code === "CUSTOMER_MESSAGE_CHANGED") { await openInquiry(inquiry.inquiry_id); error.message = "客户已发来新消息。已刷新会话，请阅读后重新提交回复。"; }
      throw error;
    }
  });
});
Object.entries(faultModes).forEach(([value]) => { const option = node("option", value); option.value = value; $("#fault-mode").append(option); });
function faultDescription() {
  const form = $("#fault-form"), slow = form.elements.mode.value === "SLOW_RESPONSE";
  $("#fault-description").textContent = faultModes[form.elements.mode.value];
  form.elements.delay_ms.disabled = !slow; form.elements.delay_ms.min = slow ? "1" : "0";
  form.elements.delay_ms.value = slow ? "1000" : "0";
}
$("#fault-mode").addEventListener("change", faultDescription); faultDescription();
$("#fault-form select[name=system]").addEventListener("change", event => { $("#fault-form").elements.record_id.value = event.target.value === "warehouse" ? "ORD-DEMO-009" : "TRK-DEMO-008-1"; });
async function loadFaults() {
  try {
    const {data} = await api("/api/admin/scenarios"); $("#fault-list").replaceChildren();
    if (!data.length) $("#fault-list").append(node("p", "暂无显式覆盖。S08 物流超时、S09 仓库不可用仍是基准行为。"));
    data.forEach(fault => {
      const card = node("div", undefined, "message");
      card.append(node("strong", `${fault.system} · ${fault.record_id}`), node("p", `${fault.mode} · 延迟 ${fault.delay_ms} ms · 剩余失败次数 ${fault.remaining_failures ?? "不限 / 不适用"}`));
      const button = node("button", "编辑此覆盖", "secondary");
      button.addEventListener("click", () => { const form = $("#fault-form"); form.elements.system.value = fault.system; form.elements.record_id.value = fault.record_id; form.elements.mode.value = fault.mode; faultDescription(); form.elements.delay_ms.value = fault.delay_ms; });
      card.append(button); $("#fault-list").append(card);
    });
  } catch (error) { $("#fault-list").textContent = errorText(error); }
}
$("#refresh-faults").addEventListener("click", loadFaults);
async function applyFault(clear = false) {
  const form = $("#fault-form"), record = form.elements.record_id.value.trim();
  if (!record) throw new Error("请输入来源记录 ID。");
  await api(`/api/admin/scenarios/${id(form.elements.system.value)}/${id(record)}`, clear ? "DELETE" : "PUT", clear ? undefined : {mode: form.elements.mode.value, delay_ms: Number(form.elements.delay_ms.value)});
  success(form, clear ? "已移除覆盖，恢复原始场景行为。" : "覆盖已应用。请在源数据页面重新读取接口。");
  await loadFaults(); await refreshAfterWrite();
}
$("#fault-form").addEventListener("submit", event => { event.preventDefault(); runForm(event.currentTarget, () => applyFault()); });
$("#clear-fault").addEventListener("click", () => runForm($("#fault-form"), () => applyFault(true)));
const operations = [
  {name: "OMS · 新建订单", method: "POST", path: () => "/api/admin/oms/orders", target: null, payload: t => ({order_id:"ORD-CUSTOM-001",customer_reference:null,status:"PAID",items:[{sku:"SKU-DEMO-001",product_name:"测试商品",quantity:1}],created_at:t,updated_at:null})},
  {name: "OMS · 更新订单状态", method: "PATCH", path: t => `/api/admin/oms/orders/${id(t)}`, target: "ORD-DEMO-002", payload: t => ({status:"DELIVERED",updated_at:t})},
  {name: "OMS · 新建包裹", method: "POST", path: t => `/api/admin/oms/orders/${id(t)}/parcels`, target:"ORD-DEMO-001", payload: () => ({parcel_id:"PAR-CUSTOM-001",order_id:"ORD-DEMO-001",carrier:"DemoCarrier",tracking_number:"TRK-CUSTOM-001",updated_at:null})},
  {name: "OMS · 更新包裹分配", method:"PATCH",path:t=>`/api/admin/oms/parcels/${id(t)}`,target:"PAR-DEMO-110-1",payload:t=>({carrier:"DemoCarrier",tracking_number:"TRK-CUSTOM-110",updated_at:t})},
  {name: "Logistics · 登记物流记录",method:"POST",path:()=>"/api/admin/logistics/shipments",target:null,payload:t=>({tracking_number:"TRK-CUSTOM-001",parcel_id:"PAR-CUSTOM-001",status:"NOT_COLLECTED",updated_at:t})},
  {name: "Logistics · 更新物流状态",method:"PATCH",path:t=>`/api/admin/logistics/shipments/${id(t)}`,target:"TRK-DEMO-002-1",payload:t=>({status:"DELIVERED",updated_at:t})},
  {name: "Logistics · 追加物流事件",method:"POST",path:t=>`/api/admin/logistics/shipments/${id(t)}/events`,target:"TRK-DEMO-002-1",payload:t=>({event_id:`EVT-${crypto.randomUUID()}`,parcel_id:"PAR-DEMO-002-1",status:"DELIVERED",description:"测试签收记录",occurred_at:t,updated_at:null})},
  {name: "Warehouse · 追加仓库备注",method:"POST",path:t=>`/api/admin/warehouse/orders/${id(t)}/notes`,target:"ORD-DEMO-002",payload:t=>({note_id:`NOTE-${crypto.randomUUID()}`,order_id:"ORD-DEMO-002",text:"模拟来源备注",created_at:t,updated_at:null})}
];
operations.forEach((operation, index) => { const option = node("option", operation.name); option.value = index; $("#source-operation").append(option); });
function showEndpoint() { const operation = operations[Number($("#source-operation").value)]; $("#source-endpoint").textContent = `${operation.method} ${operation.path($("#source-target").value.trim())}`; }
function prepareOperation() {
  const operation = operations[Number($("#source-operation").value)];
  $("#source-target-label").hidden = operation.target === null; $("#source-target").required = operation.target !== null;
  $("#source-target").value = operation.target || "";
  $("#source-payload").value = JSON.stringify(operation.payload(new Date().toISOString()), null, 2); showEndpoint();
}
$("#source-operation").addEventListener("change", prepareOperation); $("#source-target").addEventListener("input", showEndpoint); prepareOperation();
$("#simulation-form").addEventListener("submit", event => {
  event.preventDefault(); const form = event.currentTarget;
  runForm(form, async () => {
    const operation = operations[Number($("#source-operation").value)];
    let payload; try { payload = JSON.parse($("#source-payload").value); } catch { throw new Error("请求 JSON 格式无效，请检查引号、逗号与 null。"); }
    const result = await api(operation.path($("#source-target").value.trim()), operation.method, payload);
    jsonView($("#simulation-result"), result.data); success(form, `HTTP ${result.status} · 已写入此来源，其他来源保持独立。`); await refreshAfterWrite();
  });
});
$("#reset-form").addEventListener("submit", event => {
  event.preventDefault(); const form = event.currentTarget;
  runForm(form, async () => {
    // Do not reset while another console mutation is still in flight.
    if ([...document.querySelectorAll("form[data-busy]")].some(other => other !== form)) throw new Error("请等待其他操作完成后再重置。");
    const {data} = await api("/api/admin/reset", "POST", form.elements.clock.value === "now" ? {base_time:new Date().toISOString()} : {});
    pendingCommands.clear(); ++threadGeneration; currentInquiry = null; $("#messages").replaceChildren(); $("#latest-customer").hidden = true; $("#thread-info").textContent = "环境已重置，请重新选择会话。"; $("#send-message").reset(); $("#followup-reference").hidden = true; $("#more-messages").hidden = true;
    inquiryOffset = 0; form.reset(); success(form, `重置完成 · 来源基准时间 ${data.base_time}`);
    for (const selector of ["#send-message", "#new-inquiry", "#fault-form", "#simulation-form"]) {
      const control = $(selector); control.reset();
      const output = $(".operation-result", control); output.textContent = ""; output.className = "operation-result";
    }
    faultDescription(); prepareOperation();
    $("#simulation-result").replaceChildren(node("p", "环境已重置，请执行新的来源写入。"));
    ++customerGeneration; customerOffset = 0; $("#customer-orders").replaceChildren();
    $("#orders-page").textContent = ""; $("#prev-orders").disabled = true; $("#next-orders").disabled = true;
    await Promise.all([refreshAfterWrite(), loadFaults(), loadInquiries(), inspect(), loadPolicy()]);
  });
});
connect();
