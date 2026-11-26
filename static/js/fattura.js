// Comportamenti della pagina fattura: righe aggiuntive, termini di pagamento e rate.
// Il server ricalcola comunque tutto: questo script serve solo a rendere la compilazione più comoda.
(function () {
  "use strict";

  function aggiungiDaModello(prefisso, idModello, idCorpo) {
    var totale = document.getElementById("id_" + prefisso + "-TOTAL_FORMS");
    var indice = parseInt(totale.value, 10);
    var html = document.getElementById(idModello).innerHTML.replace(/__prefix__/g, String(indice));
    var corpo = document.getElementById(idCorpo);
    corpo.insertAdjacentHTML("beforeend", html.trim());
    totale.value = String(indice + 1);
    return corpo.lastElementChild;
  }

  // --- Righe ---------------------------------------------------------------
  document.getElementById("aggiungi-riga").addEventListener("click", function () {
    var riga = aggiungiDaModello("righe", "riga-vuota", "righe-corpo");
    var campo = riga.querySelector("input[name$='-descrizione']");
    if (campo) campo.focus();
  });

  // Scegliendo un articolo la riga prende descrizione, prezzo, u.m., aliquota e natura.
  var articoli = JSON.parse(document.getElementById("dati-articoli").textContent);
  document.getElementById("righe-corpo").addEventListener("change", function (evento) {
    var scelta = evento.target;
    if (!scelta.matches("select[name$='-articolo']")) return;
    var dati = articoli[scelta.value];
    if (!dati) return;
    var riga = scelta.closest("tr");
    ["descrizione", "unita_misura", "natura"].forEach(function (campo) {
      riga.querySelector("[name$='-" + campo + "']").value = dati[campo];
    });
    riga.querySelector("[name$='-prezzo_unitario']").value = dati.prezzo;
    riga.querySelector("[name$='-aliquota_iva']").value = dati.aliquota_iva;
  });

  // --- Termini di pagamento -------------------------------------------------
  var condizioni = document.getElementById("id_condizioni_pagamento");
  var termini = document.getElementById("id_termini_pagamento");
  var dataFattura = document.getElementById("id_data");
  var numeroRate = document.getElementById("id_numero_rate");
  var anteprima = document.getElementById("anteprima-scadenza");

  function parseData(testo) {
    var p = (testo || "").split("-");
    if (p.length !== 3) return null;
    return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
  }
  function formatoIso(d) { return d.toISOString().slice(0, 10); }
  function formatoIt(d) { return formatoIso(d).split("-").reverse().join("/"); }

  // Stessa regola del server (fatture/calcoli.py): giorni dalla data fattura, poi eventuale fine mese.
  function scadenza(base, codice, multiplo) {
    var fm = /FM$/.test(codice);
    var giorni = parseInt(fm ? codice.slice(0, -2) : codice, 10) || 0;
    var d = new Date(base.getTime() + giorni * multiplo * 86400000);
    if (fm) d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
    return d;
  }
  function passoRate(codice) {
    var fm = /FM$/.test(codice);
    var giorni = parseInt(fm ? codice.slice(0, -2) : codice, 10) || 30;
    return giorni + (fm ? "FM" : "");
  }

  function mostra(id, visibile) {
    var el = document.getElementById(id);
    if (el) el.hidden = !visibile;
  }

  function aggiorna() {
    var aRate = condizioni.value === "TP01";
    var libera = termini.value === "LIBERA";
    mostra("campo-data_scadenza", libera && !aRate);
    mostra("campo-numero_rate", aRate);
    mostra("blocco-rate", aRate);
    var base = parseData(dataFattura.value);
    anteprima.textContent = "";
    if (!aRate && !libera && base) {
      anteprima.textContent = "Scadenza calcolata: " + formatoIt(scadenza(base, termini.value, 1));
    }
    numeraRate();
  }

  // --- Rate -------------------------------------------------------------------
  function righeRate() {
    return Array.prototype.filter.call(document.querySelectorAll("#rate-corpo tr.rata"), function (tr) {
      var canc = tr.querySelector("input[name$='-DELETE']");
      return !tr.hidden && !(canc && canc.checked);
    });
  }
  function numeraRate() {
    righeRate().forEach(function (tr, i) { tr.querySelector(".numero-rata").textContent = String(i + 1); });
  }

  document.getElementById("calcola-rate").addEventListener("click", function () {
    var n = parseInt(numeroRate.value, 10);
    var base = parseData(dataFattura.value);
    if (!(n >= 2 && n <= 36) || !base) {
      numeroRate.focus();
      anteprima.textContent = "Indica una data fattura e un numero di rate da 2 a 36.";
      return;
    }
    // Le rate già salvate vengono marcate da eliminare, quelle nuove tolte dalla pagina.
    document.querySelectorAll("#rate-corpo tr.rata").forEach(function (tr) {
      var id = tr.querySelector("input[name$='-id']");
      var canc = tr.querySelector("input[name$='-DELETE']");
      if (id && id.value) { canc.checked = true; tr.hidden = true; } else { tr.remove(); }
    });
    // Ricompatta l'indice delle rate nuove dopo quelle salvate.
    var iniziali = parseInt(document.getElementById("id_rate-INITIAL_FORMS").value, 10);
    document.getElementById("id_rate-TOTAL_FORMS").value = String(iniziali);
    var passo = passoRate(termini.value);
    for (var i = 1; i <= n; i++) {
      var tr = aggiungiDaModello("rate", "rata-vuota", "rate-corpo");
      tr.querySelector("input[name$='-data_scadenza']").value = formatoIso(scadenza(base, passo, i));
    }
    numeraRate();
  });

  document.getElementById("rate-corpo").addEventListener("change", numeraRate);
  [condizioni, termini, dataFattura].forEach(function (el) { el.addEventListener("change", aggiorna); });
  aggiorna();
})();
