import React, { useState, useEffect, useMemo } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Grid from '@mui/material/Grid';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import IconButton from '@mui/material/IconButton';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Chip from '@mui/material/Chip';
import TextField from '@mui/material/TextField';
import MenuItem from '@mui/material/MenuItem';
import InputAdornment from '@mui/material/InputAdornment';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';

import FolderPlayIcon from '@mui/icons-material/FolderSpecial';
import RefreshIcon from '@mui/icons-material/Refresh';
import PlayIcon from '@mui/icons-material/PlayArrow';
import DownloadIcon from '@mui/icons-material/Download';
import TrashIcon from '@mui/icons-material/Delete';
import SearchIcon from '@mui/icons-material/Search';

import { libraryApi, LibraryItem, LibrarySource } from '../../src/api';

type SourceFilter = 'all' | LibrarySource;
type SortKey = 'newest' | 'oldest' | 'largest' | 'smallest' | 'name';

const SOURCE_LABELS: Record<LibrarySource, string> = { web: '手动制作', auto: '自动搬运' };

const SORTERS: Record<SortKey, { label: string; compare: (a: LibraryItem, b: LibraryItem) => number }> = {
  newest: { label: '最新优先', compare: (a, b) => b.mtime - a.mtime },
  oldest: { label: '最早优先', compare: (a, b) => a.mtime - b.mtime },
  largest: { label: '文件最大', compare: (a, b) => b.size_bytes - a.size_bytes },
  smallest: { label: '文件最小', compare: (a, b) => a.size_bytes - b.size_bytes },
  name: { label: '名称 A→Z', compare: (a, b) => a.name.localeCompare(b.name, 'zh-CN') },
};

// 来源筛选和排序记在浏览器里，下次打开还是同样的视图；读写失败（隐私模式等）就用默认值
const PREFS_KEY = 'library-view';

const loadPrefs = (): { source: SourceFilter; sort: SortKey } => {
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}');
    return {
      source: ['all', 'web', 'auto'].includes(saved.source) ? saved.source : 'all',
      sort: saved.sort in SORTERS ? saved.sort : 'newest',
    };
  } catch {
    return { source: 'all', sort: 'newest' };
  }
};

const savePrefs = (source: SourceFilter, sort: SortKey) => {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify({ source, sort }));
  } catch {
    // 存不了就算了，只影响下次打开时的默认视图
  }
};

// 文件名来自视频标题，可能带 # 和 ?，encodeURI 不转义它们
const mediaUrl = (path: string) =>
  encodeURI(libraryApi.getDownloadUrl(path)).replace(/#/g, '%23').replace(/\?/g, '%3F');

const filledFieldSx = {
  '& .MuiFilledInput-root': {
    borderRadius: 1.5,
    bgcolor: 'rgba(0,0,0,0.3)',
    '&:hover': { bgcolor: 'rgba(0,0,0,0.4)' },
  },
};

const LibraryPanel = () => {
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [playing, setPlaying] = useState<LibraryItem | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [sortKey, setSortKey] = useState<SortKey>('newest');
  const [query, setQuery] = useState('');
  const [clearing, setClearing] = useState(false);

  const fetchLibrary = async () => {
    setLoading(true);
    try {
      const res = await libraryApi.list();
      setItems(res.data);
    } catch (e) {
      console.error("Library sync failed:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const prefs = loadPrefs();
    setSourceFilter(prefs.source);
    setSortKey(prefs.sort);
    fetchLibrary();
  }, []);

  const changeSource = (source: SourceFilter) => {
    setSourceFilter(source);
    savePrefs(source, sortKey);
  };

  const changeSort = (sort: SortKey) => {
    setSortKey(sort);
    savePrefs(sourceFilter, sort);
  };

  const counts = useMemo(() => ({
    all: items.length,
    web: items.filter((item) => item.source === 'web').length,
    auto: items.filter((item) => item.source === 'auto').length,
  }), [items]);

  const visibleItems = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return items
      .filter((item) => sourceFilter === 'all' || item.source === sourceFilter)
      .filter((item) => !keyword || item.name.toLowerCase().includes(keyword))
      .sort(SORTERS[sortKey].compare);
  }, [items, sourceFilter, query, sortKey]);

  const deleteItem = async (item: LibraryItem) => {
    if (!confirm(`确定要永久删除「${item.name}」吗？`)) return;
    try {
      await libraryApi.delete(item.name, item.source);
      fetchLibrary();
    } catch (e) {
      alert("删除失败");
    }
  };

  // 只删当前筛选、搜索后看得到的这些，免得在筛选状态下误删别的
  const clearVisible = async () => {
    const targets = visibleItems;
    if (!confirm(`确定要永久删除当前列表中的 ${targets.length} 个视频吗？`)) return;
    if (!confirm("请再次确认：删除后无法恢复！")) return;

    setClearing(true);
    let failed = 0;
    for (const item of targets) {
      try {
        await libraryApi.delete(item.name, item.source);
      } catch (e) {
        failed += 1;
      }
    }
    setClearing(false);
    if (failed) alert(`有 ${failed} 个删除失败`);
    fetchLibrary();
  };

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 4, animate: 'fadeIn 0.5s ease-out' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', px: 2 }}>
        <Typography
          variant="h4"
          sx={{
            fontWeight: 900,
            display: 'flex',
            alignItems: 'center',
            gap: 2,
            color: 'white'
          }}
        >
          <FolderPlayIcon sx={{ fontSize: 40, color: 'secondary.main' }} />
          媒体库
        </Typography>
        <Stack direction="row" spacing={2}>
          <Button
            variant="contained"
            color="error"
            startIcon={clearing ? <CircularProgress size={14} color="inherit" /> : <TrashIcon />}
            onClick={clearVisible}
            disabled={visibleItems.length === 0 || clearing}
            sx={{
              fontWeight: 900,
              textTransform: 'uppercase',
              fontSize: 10,
              letterSpacing: 1,
              px: 3,
              borderRadius: 1
            }}
          >
            Clear Hub
          </Button>
          <Button
            variant="contained"
            color="inherit"
            startIcon={<RefreshIcon />}
            onClick={fetchLibrary}
            sx={{
              bgcolor: 'white',
              color: 'black',
              fontWeight: 900,
              textTransform: 'uppercase',
              fontSize: 10,
              letterSpacing: 2,
              fontStyle: 'italic',
              px: 3,
              borderRadius: 1,
              '&:hover': { bgcolor: 'secondary.main', color: 'white' }
            }}
          >
            Refresh HUB
          </Button>
        </Stack>
      </Box>

      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 2, px: 2 }}>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={sourceFilter}
          onChange={(_, value: SourceFilter | null) => value && changeSource(value)}
          sx={{
            bgcolor: 'rgba(0,0,0,0.3)',
            '& .MuiToggleButton-root': { px: 2, fontWeight: 700, border: '1px solid rgba(255,255,255,0.08)' },
            '& .Mui-selected': { color: 'secondary.main' },
          }}
        >
          <ToggleButton value="all">全部 {counts.all}</ToggleButton>
          <ToggleButton value="web">{SOURCE_LABELS.web} {counts.web}</ToggleButton>
          <ToggleButton value="auto">{SOURCE_LABELS.auto} {counts.auto}</ToggleButton>
        </ToggleButtonGroup>

        <TextField
          size="small"
          variant="filled"
          hiddenLabel
          placeholder="搜索标题"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          sx={{ ...filledFieldSx, flex: '1 1 220px', maxWidth: 420 }}
          slotProps={{
            input: {
              disableUnderline: true,
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" sx={{ color: 'text.secondary' }} />
                </InputAdornment>
              ),
            },
          }}
        />

        <TextField
          select
          size="small"
          variant="filled"
          hiddenLabel
          value={sortKey}
          onChange={(e) => changeSort(e.target.value as SortKey)}
          sx={{ ...filledFieldSx, minWidth: 140, '& .MuiSelect-select': { fontWeight: 700 } }}
          slotProps={{ input: { disableUnderline: true } }}
        >
          {(Object.keys(SORTERS) as SortKey[]).map((key) => (
            <MenuItem key={key} value={key}>{SORTERS[key].label}</MenuItem>
          ))}
        </TextField>

        {!loading && items.length > 0 && (
          <Typography variant="caption" sx={{ color: 'text.secondary', ml: 'auto' }}>
            显示 {visibleItems.length} / {items.length}
          </Typography>
        )}
      </Box>

      {loading ? (
        <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyItems: 'center', justifyContent: 'center' }}>
          <CircularProgress color="secondary" size={60} />
        </Box>
      ) : items.length === 0 ? (
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', opacity: 0.1 }}>
          <FolderPlayIcon sx={{ fontSize: 120, mb: 4 }} />
          <Typography variant="h4" sx={{ fontWeight: 900, letterSpacing: 10, textTransform: 'uppercase' }}>Storage Empty</Typography>
        </Box>
      ) : visibleItems.length === 0 ? (
        <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Typography variant="h6" sx={{ color: 'text.secondary', fontWeight: 700 }}>没有符合条件的视频</Typography>
        </Box>
      ) : (
        <Box sx={{ flex: 1, overflow: 'auto', pr: 2, '&::-webkit-scrollbar': { width: 8 }, '&::-webkit-scrollbar-thumb': { bgcolor: 'rgba(255,255,255,0.1)', borderRadius: 1 } }}>
          <Grid container spacing={4} sx={{ pb: 10 }}>
            {visibleItems.map((item) => (
              <Grid size={{ xs: 12, sm: 6, md: 4, lg: 3 }} key={`${item.source}/${item.name}`}>
                <Card
                  sx={{
                    bgcolor: 'rgba(255, 255, 255, 0.03)',
                    borderRadius: 1.5,
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    transition: 'all 0.3s ease',
                    '&:hover': { transform: 'translateY(-10px)', bgcolor: 'rgba(255,255,255,0.05)' }
                  }}
                >
                  <Box
                    sx={{
                      aspectRatio: '16/9',
                      bgcolor: 'black',
                      backgroundImage: `url("${mediaUrl(item.thumbnail)}")`,
                      backgroundSize: 'cover',
                      backgroundPosition: 'center',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      cursor: 'pointer',
                      position: 'relative',
                      '&:hover .play-overlay': { opacity: 1 }
                    }}
                    onClick={() => setPlaying(item)}
                  >
                    <Chip
                      label={SOURCE_LABELS[item.source]}
                      size="small"
                      color={item.source === 'auto' ? 'secondary' : 'default'}
                      sx={{
                        position: 'absolute',
                        top: 8,
                        left: 8,
                        zIndex: 1,
                        fontWeight: 900,
                        fontSize: 11,
                        ...(item.source === 'web' && { bgcolor: 'rgba(0,0,0,0.65)', color: 'white' }),
                      }}
                    />
                    <Box
                      className="play-overlay"
                      sx={{
                        position: 'absolute',
                        inset: 0,
                        bgcolor: 'rgba(0,0,0,0.4)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        opacity: 0,
                        transition: 'opacity 0.3s ease'
                      }}
                    >
                      <PlayIcon sx={{ fontSize: 60, color: 'white' }} />
                    </Box>
                  </Box>
                  <CardContent sx={{ p: 3 }}>
                    <Typography
                      variant="subtitle2"
                      sx={{
                        fontWeight: 700,
                        color: 'text.primary',
                        mb: 2,
                        lineClamp: 2,
                        display: '-webkit-box',
                        WebkitBoxOrient: 'vertical',
                        WebkitLineClamp: 2,
                        overflow: 'hidden',
                        height: 40
                      }}
                    >
                      {item.name}
                    </Typography>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Box sx={{ display: 'flex', flexDirection: 'column' }}>
                        <Typography variant="caption" sx={{ fontStyle: 'italic', color: 'text.secondary', fontWeight: 900 }}>
                          {item.size}
                        </Typography>
                        <Typography variant="caption" sx={{ color: 'text.secondary', opacity: 0.8 }}>
                          {item.time}
                        </Typography>
                      </Box>
                      <Stack direction="row" spacing={1}>
                        <IconButton
                          size="small"
                          href={mediaUrl(item.path)}
                          download={item.name}
                          sx={{ bgcolor: 'rgba(255,255,255,0.05)', '&:hover': { bgcolor: 'secondary.main', color: 'white' } }}
                        >
                          <DownloadIcon fontSize="small" />
                        </IconButton>
                        <IconButton
                          size="small"
                          onClick={() => deleteItem(item)}
                          sx={{ bgcolor: 'rgba(255,255,255,0.05)', '&:hover': { bgcolor: 'error.main', color: 'white' } }}
                        >
                          <TrashIcon fontSize="small" />
                        </IconButton>
                      </Stack>
                    </Box>
                  </CardContent>
                </Card>
              </Grid>
            ))}
          </Grid>
        </Box>
      )}

      <Dialog
        fullWidth
        maxWidth="lg"
        open={Boolean(playing)}
        onClose={() => setPlaying(null)}
        PaperProps={{
          sx: {
            bgcolor: 'black',
            borderRadius: 2,
            overflow: 'hidden',
            border: '1px solid rgba(255, 255, 255, 0.1)'
          }
        }}
      >
        {playing && (
          <Box sx={{ display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ position: 'relative', width: '100%', aspectRatio: '16/9', bgcolor: 'black' }}>
               <video
                 src={mediaUrl(playing.path)}
                 controls
                 autoPlay
                 style={{ width: '100%', height: '100%', objectFit: 'contain' }}
               />
            </Box>
            <Paper sx={{ p: 4, bgcolor: 'rgba(10, 12, 20, 0.9)', borderTop: '1px solid rgba(255, 255, 255, 0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderRadius: 0 }}>
               <Typography variant="h6" sx={{ fontWeight: 900, fontStyle: 'italic', textTransform: 'uppercase', maxWidth: '70%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                 {playing.name}
               </Typography>
               <Button
                 variant="contained"
                 color="error"
                 onClick={() => setPlaying(null)}
                 sx={{ px: 6, fontWeight: 900, borderRadius: 2 }}
               >
                 Close Theater
               </Button>
            </Paper>
          </Box>
        )}
      </Dialog>
    </Box>
  );
};

export default LibraryPanel;
