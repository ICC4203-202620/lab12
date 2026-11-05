const form = document.querySelector("#message-form");
const field = document.querySelector("#message");
const send = document.querySelector("#send");
const reload = document.querySelector("#reload");
const status = document.querySelector("#status");
const list = document.querySelector("#messages");
const empty = document.querySelector("#empty");

function inform(text, error = false) {
  status.textContent = text;
  status.dataset.error = String(error);
}

async function request(options = {}) {
  const response = await fetch("/api/mensajes", { cache: "no-store", ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "No fue posible completar la solicitud.");
  return data;
}

async function loadMessages() {
  const data = await request();
  list.replaceChildren();
  for (const message of data.mensajes) {
    const item = document.createElement("li");
    const text = document.createElement("p");
    text.textContent = message.texto;
    const date = document.createElement("time");
    date.dateTime = message.creado_en;
    date.textContent = new Date(message.creado_en).toLocaleString("es-CL");
    item.append(text, date);
    list.append(item);
  }
  empty.hidden = data.mensajes.length > 0;
  empty.textContent = "Todavía no hay mensajes guardados.";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const texto = field.value.trim();
  if (!texto) return inform("Se debe escribir un mensaje.", true);
  send.disabled = true;
  let saved = false;
  try {
    await request({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto }) });
    saved = true;
    field.value = "";
    await loadMessages();
    inform("Mensaje guardado en la base de datos.");
  } catch (error) {
    inform(saved ? "El mensaje se guardó, pero no se pudo actualizar la lista. Utilizar Actualizar." : error.message, true);
  } finally {
    send.disabled = false;
  }
});

async function refresh() {
  reload.disabled = true;
  try {
    await loadMessages();
    inform("Lista actualizada.");
  } catch (error) {
    empty.textContent = "No fue posible consultar los mensajes. Comprobar la preparación de DSQL.";
    inform(error.message, true);
  } finally {
    reload.disabled = false;
  }
}

reload.addEventListener("click", refresh);
refresh();
