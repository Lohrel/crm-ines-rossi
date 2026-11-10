// Listas longas (etapa 21): filtro de uma lista ou tabela e "Marcar todas" nas caixas de marcar.
(function () {
  function sem_acento(texto) {
    return texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  document.querySelectorAll("input.filtro-de-linhas[data-filtra]").forEach(function (campo) {
    var lista = document.querySelector(campo.dataset.filtra);
    if (!lista) return;
    // Linhas de uma tabela ou itens marcados com data-item-filtro.
    var linhas = Array.prototype.slice.call(
      lista.tBodies ? lista.tBodies[0].rows : lista.querySelectorAll("[data-item-filtro]")
    );
    var textos = linhas.map(function (linha) { return sem_acento(linha.textContent); });
    var aviso = lista.parentElement.querySelector(".nenhuma-linha");
    campo.addEventListener("input", function () {
      var palavras = sem_acento(campo.value).replace(/[.\/-]/g, "").split(/\s+/).filter(Boolean);
      var visiveis = 0;
      linhas.forEach(function (linha, i) {
        var texto = textos[i] + " " + textos[i].replace(/[.\/-]/g, "");
        var mostra = palavras.every(function (p) { return texto.indexOf(p) !== -1; });
        linha.hidden = !mostra;
        if (mostra) visiveis += 1;
      });
      if (aviso) aviso.hidden = visiveis > 0;
    });
  });

  document.querySelectorAll("[data-marcar-todas]").forEach(function (botao) {
    botao.addEventListener("click", function () {
      var grupo = document.getElementById(botao.dataset.marcarTodas);
      var marcar = botao.dataset.valor === "1";
      grupo.querySelectorAll("input[type=checkbox]").forEach(function (caixa) {
        caixa.checked = marcar;
      });
    });
  });
})();
