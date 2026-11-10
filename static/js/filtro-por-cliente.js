// Relatórios: ao escolher a empresa, as listas de filial e de contrato mostram só as dela.
// Cada opção traz o cliente em data-cliente (relatorios/forms.py, SelectDoCliente).
(function () {
  "use strict";

  const cliente = document.querySelector("select[name=cliente]");
  const listas = document.querySelectorAll("select[data-filtra-pelo-cliente]");
  if (!cliente || !listas.length) return;

  // Guarda a lista completa, para refazer a cada troca de empresa (esconder <option> com CSS
  // não funciona em todos os navegadores).
  const originais = Array.from(listas, function (lista) {
    return lista.cloneNode(true);
  });

  function filtrar() {
    const escolhido = cliente.value;
    listas.forEach(function (lista, i) {
      const valor = lista.value;
      lista.replaceChildren(...Array.from(originais[i].children, function (filho) {
        return filho.cloneNode(true);
      }));
      if (escolhido) {
        lista.querySelectorAll("option[data-cliente]").forEach(function (opcao) {
          if (opcao.dataset.cliente !== escolhido) opcao.remove();
        });
        lista.querySelectorAll("optgroup").forEach(function (grupo) {
          if (!grupo.children.length) grupo.remove();
        });
      }
      lista.value = valor;
      if (lista.value !== valor) lista.value = "";
    });
  }

  cliente.addEventListener("change", filtrar);
  filtrar();
})();
