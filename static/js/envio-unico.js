// Formulários de cadastro (data-envio-unico): um clique duplo em "Salvar" não envia duas vezes.
// Sem isso, a pessoa (e os pedidos de inclusão dela) podiam ser gravados em dobro.
(function () {
  document.addEventListener("submit", function (evento) {
    var form = evento.target;
    if (!form.matches || !form.matches("form[data-envio-unico]")) return;
    if (form.dataset.enviando) {
      evento.preventDefault();
      return;
    }
    form.dataset.enviando = "1";
  });
  // Ao voltar para a página pelo botão Voltar do navegador, o formulário pode ser enviado de novo.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-envio-unico]").forEach(function (form) {
      delete form.dataset.enviando;
    });
  });
})();
