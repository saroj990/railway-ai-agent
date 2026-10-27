const chatEl = document.getElementById("chat");
const formEl = document.getElementById("composer");
const inputEl = document.getElementById("message");
const sendEl = document.getElementById("send");
const statusEl = document.getElementById("status");
const welcomeEl = document.getElementById("welcome");
const welcomeHTML = welcomeEl ? welcomeEl.outerHTML : "";
const STORAGE_KEY = "rail_session_id";

let sessionId = localStorage.getItem(STORAGE_KEY);
let busy = false;

/* ------------------------------------------------------------------ utils */
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}

function inline(text) {
  return text
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|\s)_([^_]+)_(?=\s|$|[.,;:!?])/g, "$1<em>$2</em>");
}

function splitRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableStart(lines, index) {
  if (index + 1 >= lines.length) return false;
  const header = lines[index];
  const divider = lines[index + 1];
  return (
    header.includes("|") &&
    divider.includes("-") &&
    /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(divider)
  );
}

function renderMarkdown(markdown) {
  const text = escapeHtml(markdown).replace(/\r\n/g, "\n");
  const lines = text.split("\n");
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i += 1;
      continue;
    }

    if (isTableStart(lines, i)) {
      const header = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        rows.push(splitRow(lines[i]));
        i += 1;
      }
      const head = header.map((cell) => `<th>${inline(cell)}</th>`).join("");
      const body = rows
        .map(
          (row) =>
            `<tr>${header
              .map((_, index) => `<td>${inline(row[index] || "—")}</td>`)
              .join("")}</tr>`
        )
        .join("");
      out.push(
        `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
      );
      continue;
    }

    const heading = line.match(/^#{1,3}\s+(.*)$/);
    if (heading) {
      out.push(`<h3>${inline(heading[1])}</h3>`);
      i += 1;
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ""))}</li>`);
        i += 1;
      }
      out.push(`<ul>${items.join("")}</ul>`);
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^\s*\d+\.\s+/, ""))}</li>`);
        i += 1;
      }
      out.push(`<ol>${items.join("")}</ol>`);
      continue;
    }

    const paragraph = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !isTableStart(lines, i) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^#{1,3}\s+/.test(lines[i])
    ) {
      paragraph.push(lines[i]);
      i += 1;
    }
    out.push(`<p>${inline(paragraph.join(" "))}</p>`);
  }

  return out.join("");
}

/* ------------------------------------------------------------- chat render */
function hideWelcome() {
  if (welcomeEl && welcomeEl.isConnected) welcomeEl.remove();
}

function scrollToBottom() {
  chatEl.scrollTop = chatEl.scrollHeight;
}

function addMessage(role, className) {
  const wrapper = document.createElement("div");
  wrapper.className = `msg ${className || role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  wrapper.appendChild(bubble);
  chatEl.appendChild(wrapper);
  scrollToBottom();
  return bubble;
}

function appendSources(bubble, sources) {
  if (!sources || !sources.length) return;
  const details = document.createElement("details");
  details.className = "sources";
  const summary = document.createElement("summary");
  summary.textContent = "Data source";
  details.appendChild(summary);
  const list = document.createElement("ul");
  sources.forEach((source) => {
    const item = document.createElement("li");
    const bits = [source.source || "Imported timetable", source.kind || "scheduled"];
    if (source.dataset_date) bits.push(`dataset ${source.dataset_date}`);
    if (source.retrieved_at) bits.push(`imported ${String(source.retrieved_at).slice(0, 10)}`);
    item.textContent = bits.join(" · ");
    list.appendChild(item);
  });
  details.appendChild(list);
  bubble.appendChild(details);
}

function appendAssistant(data) {
  const bubble = addMessage("assistant");
  bubble.innerHTML = renderMarkdown(data.reply || "");
  appendDataBlock(bubble, data.tool_results || [], data.reply || "");
  appendSources(bubble, data.sources);
  scrollToBottom();
}

/* --------------------------------------------------- structured tool tables */
function tableFrom(headers, rows) {
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach((label) => {
    const th = document.createElement("th");
    th.textContent = label;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  rows.forEach((cells) => {
    const tr = document.createElement("tr");
    cells.forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  wrap.appendChild(table);
  return wrap;
}

function tableRowCount(reply) {
  const lines = reply.split("\n").filter((line) => line.trim().startsWith("|"));
  return Math.max(0, lines.length - 2);
}

function dataTableFor(result) {
  if (!result || !result.ok || !result.data) return null;
  const data = result.data;
  if (result.tool === "search_trains" || result.tool === "compare_trains") {
    const trains = data.trains || [];
    if (!trains.length) return null;
    return {
      expected: trains.length,
      node: tableFrom(
        ["Train", "Name", "Departs", "Arrives", "Duration", "Stops en route", "Km"],
        trains.map((train) => [
          train.train_number,
          train.train_name,
          train.departure,
          train.arrival,
          formatDuration(train.duration_minutes),
          train.stops,
          train.distance_km,
        ])
      ),
    };
  }
  if (result.tool === "get_train_schedule" || result.tool === "get_train_route") {
    const stops = data.stops || [];
    if (!stops.length) return null;
    return {
      expected: stops.length,
      node: tableFrom(
        ["#", "Station", "Arrives", "Departs", "Halt", "Day", "Km"],
        stops.map((stop) => [
          stop.sequence,
          `${stop.station_name} (${stop.station_code})`,
          stop.arrival,
          stop.departure,
          stop.halt_minutes === null || stop.halt_minutes === undefined
            ? null
            : `${stop.halt_minutes}m`,
          stop.day,
          stop.distance_km,
        ])
      ),
    };
  }
  return null;
}

function formatDuration(minutes) {
  if (minutes === null || minutes === undefined) return "—";
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hours && mins) return `${hours}h ${String(mins).padStart(2, "0")}m`;
  if (hours) return `${hours}h`;
  return `${mins}m`;
}

function appendDataBlock(bubble, results, reply) {
  const replyRows = tableRowCount(reply);
  const tables = results.map(dataTableFor).filter(Boolean);
  if (!tables.length) return;
  const expected = Math.max(...tables.map((item) => item.expected));
  if (replyRows >= expected) return; // the answer already shows every row

  const block = document.createElement("div");
  block.className = "data-block";
  const title = document.createElement("p");
  title.className = "data-title";
  title.textContent = "Complete data from the timetable";
  block.appendChild(title);
  tables.forEach((item) => block.appendChild(item.node));
  bubble.appendChild(block);
}

function appendError(message) {
  const bubble = addMessage("assistant", "error");
  bubble.textContent = message;
}

function appendTyping() {
  const bubble = addMessage("assistant");
  bubble.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
  bubble.dataset.typing = "true";
  return bubble.closest(".msg");
}

function setBusy(value) {
  busy = value;
  sendEl.disabled = value;
  inputEl.disabled = value;
  sendEl.textContent = value ? "…" : "Send";
}

/* -------------------------------------------------------------------- send */
async function sendMessage(text) {
  const message = text.trim();
  if (!message || busy) return;

  hideWelcome();
  const userBubble = addMessage("user");
  userBubble.textContent = message;
  inputEl.value = "";
  inputEl.style.height = "auto";
  const typing = appendTyping();
  setBusy(true);

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: sessionId || undefined,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `Request failed (HTTP ${response.status}).`);
    }
    if (data.session_id) {
      sessionId = data.session_id;
      localStorage.setItem(STORAGE_KEY, sessionId);
    }
    typing.remove();
    appendAssistant(data);
  } catch (error) {
    typing.remove();
    appendError(
      error instanceof Error ? error.message : "Something went wrong. Please try again."
    );
  } finally {
    setBusy(false);
    inputEl.focus();
  }
}

/* ----------------------------------------------------------------- events */
formEl.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(inputEl.value);
});

inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    formEl.requestSubmit();
  }
});

inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, 160)}px`;
});

chatEl.addEventListener("click", (event) => {
  const target = event.target;
  if (target instanceof HTMLElement && target.classList.contains("chip")) {
    sendMessage(target.textContent || "");
  }
});

document.getElementById("new-chat").addEventListener("click", () => {
  sessionId = null;
  localStorage.removeItem(STORAGE_KEY);
  chatEl.innerHTML = welcomeHTML;
  inputEl.value = "";
  inputEl.focus();
});

/* ------------------------------------------------------------------ health */
async function loadHealth() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    const dataset = data.dataset || {};
    if (dataset.status === "ok") {
      const label = `Data: ${Number(dataset.trains).toLocaleString()} trains · ${
        dataset.dataset_date ? `dataset ${dataset.dataset_date}` : "dataset date unknown"
      } · ${data.llm_provider}${data.llm_model ? ` (${data.llm_model})` : ""}`;
      statusEl.textContent = label;
    } else if (dataset.status === "missing") {
      statusEl.textContent = "Timetable not imported — run the importer.";
    } else {
      statusEl.textContent = data.detail ? `Degraded: ${data.detail}` : "Data source degraded.";
    }
  } catch {
    statusEl.textContent = "Backend unreachable.";
  }
}

loadHealth();
inputEl.focus();
