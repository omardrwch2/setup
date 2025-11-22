return {
  {
    "lewis6991/gitsigns.nvim",
    opts = {
      signs = {
        add          = { text = '│' },
        change       = { text = '│' },
        delete       = { text = '_' },
        topdelete    = { text = '‾' },
        changedelete = { text = '~' },
      },
      on_attach = function(bufnr)
        local gs = package.loaded.gitsigns

        local function map(mode, l, r, opts)
          opts = opts or {}
          opts.buffer = bufnr
          vim.keymap.set(mode, l, r, opts)
        end

        -- Navigation
        map('n', ']c', function()
          if vim.wo.diff then return ']c' end
          vim.schedule(function() gs.next_hunk() end)
          return '<Ignore>'
        end, {expr=true, desc="Next git hunk"})

        map('n', '[c', function()
          if vim.wo.diff then return '[c' end
          vim.schedule(function() gs.prev_hunk() end)
          return '<Ignore>'
        end, {expr=true, desc="Previous git hunk"})

        -- Actions
        map('n', '<leader>gp', gs.preview_hunk, {desc="Preview git hunk"})
        map('n', '<leader>gb', gs.blame_line, {desc="Git blame line"})
        map('n', '<leader>gd', gs.diffthis, {desc="Git diff this"})
        map('n', '<leader>gr', gs.reset_hunk, {desc="Reset git hunk"})
        map('n', '<leader>gR', gs.reset_buffer, {desc="Reset git buffer"})
      end
    },
  },
}

