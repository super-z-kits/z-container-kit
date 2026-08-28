# Testing the helpers safely

ZK_PROJ / ZK_SYNC env overrides for scratch testing.
Extracted from SKILL.md v2.3.3.
## Testing the helpers safely

The helpers honor overrides so tests never touch the real `/home/sync`
artifacts (an accidental real zsave would overwrite `/home/sync/repo.tar` —
the boot-restore artifact — with whatever the project contains at that
moment):

```
S=/tmp/my-project/helper-test; mkdir -p $S/demo $S/sync
cd $S/demo && git init -q -b main && git commit -q --allow-empty -m init
ZK_PROJ=$S/demo ZK_SYNC=$S/sync bash /home/z/my-project/scripts/zsave "test"
ZK_PROJ=$S/demo ZK_SYNC=$S/sync bash /home/z/my-project/scripts/zsession
```
