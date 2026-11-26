// Pagina DDT: aggiunta ed eliminazione righe, compilazione dai dati dell'articolo.
(function () {
  "use strict";
  var corpo = document.getElementById("righe-corpo");
  var articoli = JSON.parse(document.getElementById("dati-articoli").textContent);

  document.getElementById("aggiungi-riga").addEventListener("click", function () {
    var totale = document.getElementById("id_righe-TOTAL_FORMS");
    var indice = parseInt(totale.value, 10);
    var html = document.getElementById("riga-vuota").innerHTML.replace(/__prefix__/g, String(indice));
    corpo.insertAdjacentHTML("beforeend", html.trim());
    totale.value = String(indice + 1);
    var campo = corpo.lastElementChild.querySelector("select[name$='-articolo']");
    if (campo) campo.focus();
  });

  corpo.addEventListener("change", function (evento) {
    var scelta = evento.target;
    if (!scelta.matches("select[name$='-articolo']")) return;
    var dati = articoli[scelta.value];
    if (!dati) return;
    var riga = scelta.closest("tr");
    riga.querySelector("[name$='-descrizione']").value = dati.descrizione;
    riga.querySelector("[name$='-unita_misura']").value = dati.unita_misura;
    riga.querySelector("[name$='-prezzo_unitario']").value = dati.prezzo;
  });

  corpo.addEventListener("click", function (evento) {
    var pulsante = evento.target.closest(".elimina-riga");
    if (!pulsante || !window.confirm("Eliminare questa riga?")) return;
    var tr = pulsante.closest("tr");
    tr.querySelector("input[name$='-DELETE']").checked = true;
    tr.hidden = true;
  });
})();
