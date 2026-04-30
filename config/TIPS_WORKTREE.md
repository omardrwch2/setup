#  Git worktrees 

```
git worktree list                              # list all worktrees
git worktree add <path> <branch>               # existing branch
git worktree add -b <new-branch> <path>        # new branch
git worktree add <path> -b <branch> origin/<branch>  # from remote
git worktree remove <path>                     # remove
git worktree remove --force <path>             # force remove if dirty
git worktree move <path> <new-path>            # relocate
git worktree prune                             # clean stale metadata
git worktree lock <path> / unlock <path>       # prevent pruning
```

#  Graphite in a worktree 

```
gt log                                         # view stack (works in any worktree)
gt create <branch>                             # new stack entry
gt checkout <branch>                           # switch (fails if checked out elsewhere)
gt sync                                        # pull + restack; run from main worktree
gt restack                                     # rebase stack; run from main worktree
gt submit                                      # push + PR
```

#  tmux pairing 

```
tmux new-session -A -s <name> -c <path>        # attach or create session in worktree
```


#  Common pattern 

```
git worktree add ../proj-feature-x -b feature-x
tmux new-session -A -s feature-x -c ../proj-feature-x
```

