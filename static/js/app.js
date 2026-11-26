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
})();
