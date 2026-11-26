// Comportamenti comuni a tutte le pagine.
(function () {
  "use strict";
  // In un campo numerico che vale 0, il valore viene selezionato all'ingresso:
  // basta iniziare a scrivere per sostituirlo.
  document.addEventListener("focusin", function (evento) {
    var campo = evento.target;
    if (campo.matches && campo.matches("input[type=number]") && campo.value !== "" && Number(campo.value) === 0) {
      // I campi numerici non supportano select() in tutti i browser: si svuota e si ripristina se si esce senza scrivere.
      campo.dataset.valorePrecedente = campo.value;
      campo.value = "";
    }
  });
  document.addEventListener("focusout", function (evento) {
    var campo = evento.target;
    if (campo.dataset && campo.dataset.valorePrecedente !== undefined) {
      if (campo.value === "") campo.value = campo.dataset.valorePrecedente;
      delete campo.dataset.valorePrecedente;
    }
  });
  // Pulsanti data-stampa: aprono la finestra di stampa del browser.
  document.addEventListener("click", function (evento) {
    if (evento.target.closest && evento.target.closest("[data-stampa]")) window.print();
  });
  // Moduli con data-conferma: chiedono conferma prima dell'invio (es. eliminazione bozza).
  document.addEventListener("submit", function (evento) {
    var messaggio = evento.target.dataset && evento.target.dataset.conferma;
    if (messaggio && !window.confirm(messaggio)) evento.preventDefault();
  });
})();
