return {
  "sindrets/diffview.nvim",
  cmd = { "DiffviewOpen", "DiffviewFileHistory", "DiffviewClose" },
  keys = {
    { "<leader>dv", "<cmd>DiffviewOpen<cr>", desc = "Diffview: Open" },
    { "<leader>dc", "<cmd>DiffviewClose<cr>", desc = "Diffview: Close" },
    { "<leader>df", "<cmd>DiffviewFileHistory %<cr>", desc = "Diffview: File History" },
    { "<leader>db", "<cmd>DiffviewFileHistory<cr>", desc = "Diffview: Branch History" },
  },
  opts = {},
}

