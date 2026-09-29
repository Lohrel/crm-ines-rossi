// Campos de data (dd/mm/aaaa) e de mês (mm/aaaa), qualquer que seja o idioma do navegador.
// O texto digitado é o que vale; o calendário do navegador é só um atalho.
(function () {
  "use strict";

  // Enquanto a pessoa digita só números, coloca as barras: 05092026 -> 05/09/2026.
  function formatarData(valor) {
    const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(valor);
    if (iso) return iso[3] + "/" + iso[2] + "/" + iso[1];
    const partes = valor.split("/");
    if (partes.length === 1) {
      const d = valor.replace(/\D/g, "").slice(0, 8);
      if (d.length <= 2) return d;
      if (d.length <= 4) return d.slice(0, 2) + "/" + d.slice(2);
      return d.slice(0, 2) + "/" + d.slice(2, 4) + "/" + d.slice(4);
    }
    if (partes.length === 2) {
      const resto = partes[1].replace(/\D/g, "").slice(0, 6);
      if (resto.length <= 2) return partes[0] + "/" + resto;
      return partes[0] + "/" + resto.slice(0, 2) + "/" + resto.slice(2);
    }
    return valor;
  }

  // O mesmo para o mês: 092026 -> 09/2026. Mês que começa com 2 a 9 ganha o zero: 92026 -> 09/2026.
  function formatarMes(valor) {
    const iso = /^(\d{4})-(\d{2})$/.exec(valor);
    if (iso) return iso[2] + "/" + iso[1];
    if (valor.includes("/")) return valor;
    let d = valor.replace(/\D/g, "");
    if (/^[2-9]/.test(d)) d = "0" + d;
    d = d.slice(0, 6);
    return d.length <= 2 ? d : d.slice(0, 2) + "/" + d.slice(2);
  }

  function paraIso(texto) {
    const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(texto.trim());
    if (!m) return "";
    return m[3] + "-" + m[2].padStart(2, "0") + "-" + m[1].padStart(2, "0");
  }

  function paraTexto(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    return m ? m[3] + "/" + m[2] + "/" + m[1] : "";
  }

  function formatarAoDigitar(campo, formatar) {
    campo.addEventListener("input", function (evento) {
      if (evento.inputType && !evento.inputType.startsWith("insert")) return;
      campo.value = formatar(campo.value);
    });
  }

  // Clicar no campo seleciona o que está escrito, então é só digitar a nova data por cima.
  // Com o campo já em uso, o clique só posiciona o cursor, para corrigir um pedaço.
  function selecionarAoClicar(campo) {
    let jaEstavaEmUso = false;
    campo.addEventListener("mousedown", function () {
      jaEstavaEmUso = document.activeElement === campo;
    });
    campo.addEventListener("click", function () {
      if (!jaEstavaEmUso && campo.selectionStart === campo.selectionEnd) campo.select();
    });
  }

  document.querySelectorAll("[data-campo-mes]").forEach(function (campo) {
    formatarAoDigitar(campo, formatarMes);
    selecionarAoClicar(campo);
  });

  document.querySelectorAll("[data-campo-data]").forEach(function (campo) {
    formatarAoDigitar(campo, formatarData);
    selecionarAoClicar(campo);

    const grupo = campo.closest("[data-grupo-data]");
    const botao = grupo && grupo.querySelector("[data-abrir-calendario]");
    const calendario = grupo && grupo.querySelector("[data-calendario]");
    if (!botao || !calendario) return;
    // Navegador sem calendário: fica só o campo de texto.
    if (typeof calendario.showPicker !== "function") {
      botao.remove();
      return;
    }

    botao.hidden = false;
    botao.addEventListener("click", function () {
      calendario.value = paraIso(campo.value);
      try {
        calendario.showPicker();
      } catch (erro) {
        botao.remove();
        campo.focus();
      }
    });
    calendario.addEventListener("change", function () {
      if (calendario.value) campo.value = paraTexto(calendario.value);
      campo.focus();
      campo.select();
    });
  });
})();
