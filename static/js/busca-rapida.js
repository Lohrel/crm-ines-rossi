// Busca rápida do menu: a tecla "/" põe o cursor no campo de busca, em qualquer tela,
// desde que a pessoa não esteja digitando em outro campo.
(function () {
  "use strict";

  document.addEventListener("keydown", function (evento) {
    if (evento.key !== "/" || evento.ctrlKey || evento.metaKey || evento.altKey) return;
    const alvo = evento.target;
    if (alvo.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName)) return;
    const campo = document.getElementById("busca-rapida");
    if (!campo || campo.offsetParent === null) return;
    evento.preventDefault();
    campo.focus();
    campo.select();
  });
})();
