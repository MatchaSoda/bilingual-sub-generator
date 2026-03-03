import React, { useState, useEffect } from 'react';
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

import FolderPlayIcon from '@mui/icons-material/FolderSpecial';
import RefreshIcon from '@mui/icons-material/Refresh';
import PlayIcon from '@mui/icons-material/PlayArrow';
import DownloadIcon from '@mui/icons-material/Download';
import TrashIcon from '@mui/icons-material/Delete';

import { libraryApi } from '../../src/api';

const LibraryPanel = () => {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [playing, setPlaying] = useState<any | null>(null);

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

  const deleteItem = async (name: string) => {
    if (!confirm("确定要永久删除吗？")) return;
    try {
      await libraryApi.delete(name);
      fetchLibrary();
    } catch (e) { 
      alert("删除失败"); 
    }
  };

  const clearLibrary = async () => {
    if (!confirm("确定要清空媒体库吗？所有视频和字幕文件都将被永久删除。")) return;
    if (!confirm("请再次确认：删除后无法恢复！")) return;
    
    try {
      await libraryApi.clear();
      fetchLibrary();
    } catch (e) { 
      alert("清空失败"); 
    }
  };

  useEffect(() => { 
    fetchLibrary(); 
  }, []);

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
            startIcon={<TrashIcon />}
            onClick={clearLibrary}
            disabled={items.length === 0}
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
      
      {loading ? (
        <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyItems: 'center', justifyContent: 'center' }}>
          <CircularProgress color="secondary" size={60} />
        </Box>
      ) : items.length === 0 ? (
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', opacity: 0.1 }}>
          <FolderPlayIcon sx={{ fontSize: 120, mb: 4 }} />
          <Typography variant="h4" sx={{ fontWeight: 900, letterSpacing: 10, textTransform: 'uppercase' }}>Storage Empty</Typography>
        </Box>
      ) : (
        <Box sx={{ flex: 1, overflow: 'auto', pr: 2, '&::-webkit-scrollbar': { width: 8 }, '&::-webkit-scrollbar-thumb': { bgcolor: 'rgba(255,255,255,0.1)', borderRadius: 1 } }}>
          <Grid container spacing={4} sx={{ pb: 10 }}>
            {items.map((item, idx) => (
              <Grid size={{ xs: 12, sm: 6, md: 4, lg: 3 }} key={idx}>
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
                      backgroundImage: `url("${encodeURI(libraryApi.getDownloadUrl(item.thumbnail)).replace(/#/g, '%23').replace(/\?/g, '%3F')}")`,
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
                          href={libraryApi.getDownloadUrl(item.path)} 
                          sx={{ bgcolor: 'rgba(255,255,255,0.05)', '&:hover': { bgcolor: 'secondary.main', color: 'white' } }}
                        >
                          <DownloadIcon fontSize="small" />
                        </IconButton>
                        <IconButton 
                          size="small" 
                          onClick={() => deleteItem(item.name)}
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
                 src={encodeURI(libraryApi.getDownloadUrl(playing.path)).replace(/#/g, '%23').replace(/\?/g, '%3F')} 
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
