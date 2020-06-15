# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/09_vision.augment.ipynb (unless otherwise specified).

__all__ = ['RandTransform', 'TensorTypes', 'FlipItem', 'DihedralItem', 'PadMode', 'CropPad', 'RandomCrop',
           'OldRandomCrop', 'ResizeMethod', 'Resize', 'RandomResizedCrop', 'RatioResize', 'AffineCoordTfm',
           'RandomResizedCropGPU', 'affine_mat', 'mask_tensor', 'flip_mat', 'Flip', 'DeterministicDraw',
           'DeterministicFlip', 'dihedral_mat', 'Dihedral', 'DeterministicDihedral', 'rotate_mat', 'Rotate', 'zoom_mat',
           'Zoom', 'find_coeffs', 'apply_perspective', 'Warp', 'LightingTfm', 'Brightness', 'Contrast',
           'cutout_gaussian', 'norm_apply_denorm', 'RandomErasing', 'setup_aug_tfms', 'aug_transforms']

# Cell
from ..data.all import *
from .core import *
from .data import *

# Cell
from torch import stack, zeros_like as t0, ones_like as t1
from torch.distributions.bernoulli import Bernoulli

# Cell
class RandTransform(Transform):
    "A transform that before_call its state at each `__call__`"
    do,nm,supports,split_idx = True,None,[],0
    def __init__(self, p=1., nm=None, before_call=None, **kwargs):
        super().__init__(**kwargs)
        self.p,self.before_call = p,ifnone(before_call,self.before_call)

    def before_call(self, b, split_idx):
        "before_call the state for input `b`"
        self.do = self.p==1. or random.random() < self.p

    def __call__(self, b, split_idx=None, **kwargs):
        self.before_call(b, split_idx=split_idx)
        return super().__call__(b, split_idx=split_idx, **kwargs) if self.do else b

# Cell
def _neg_axis(x, axis):
    x[...,axis] = -x[...,axis]
    return x

TensorTypes = (TensorImage,TensorMask,TensorPoint,TensorBBox)

# Cell
@patch
def flip_lr(x:Image.Image): return x.transpose(Image.FLIP_LEFT_RIGHT)
@patch
def flip_lr(x:TensorImageBase): return x.flip(-1)
@patch
def flip_lr(x:TensorPoint): return TensorPoint(_neg_axis(x.clone(), 0))
@patch
def flip_lr(x:TensorBBox):  return TensorBBox(TensorPoint(x.view(-1,2)).flip_lr().view(-1,4))

# Cell
class FlipItem(RandTransform):
    "Randomly flip with probability `p`"
    def __init__(self, p=0.5): super().__init__(p=p)
    def encodes(self, x:(Image.Image,*TensorTypes)): return x.flip_lr()

# Cell
@patch
def dihedral(x:PILImage, k): return x if k==0 else x.transpose(k-1)
@patch
def dihedral(x:TensorImage, k):
        if k in [1,3,4,7]: x = x.flip(-1)
        if k in [2,4,5,7]: x = x.flip(-2)
        if k in [3,5,6,7]: x = x.transpose(-1,-2)
        return x
@patch
def dihedral(x:TensorPoint, k):
        if k in [1,3,4,7]: x = _neg_axis(x, 0)
        if k in [2,4,5,7]: x = _neg_axis(x, 1)
        if k in [3,5,6,7]: x = x.flip(1)
        return x
@patch
def dihedral(x:TensorBBox, k):
        pnts = TensorPoint(x.view(-1,2)).dihedral(k).view(-1,2,2)
        tl,br = pnts.min(dim=1)[0],pnts.max(dim=1)[0]
        return TensorBBox(torch.cat([tl, br], dim=1), img_size=x.get_meta('img_size'))

# Cell
class DihedralItem(RandTransform):
    "Randomly flip with probability `p`"
    def __init__(self, p=0.5): super().__init__(p=p)

    def before_call(self, b, split_idx):
        super().before_call(b, split_idx)
        self.k = random.randint(0,7)

    def encodes(self, x:(Image.Image,*TensorTypes)): return x.dihedral(self.k)

# Cell
from torchvision.transforms.functional import pad as tvpad

# Cell
mk_class('PadMode', **{o:o.lower() for o in ['Zeros', 'Border', 'Reflection']},
         doc="All possible padding mode as attributes to get tab-completion and typo-proofing")

# Cell
_pad_modes = {'zeros': 'constant', 'border': 'edge', 'reflection': 'reflect'}

@patch
def _do_crop_pad(x:Image.Image, sz, tl, orig_sz,
                 pad_mode=PadMode.Zeros, resize_mode=Image.BILINEAR, resize_to=None):
    if any(tl.ge(0)):
        # At least one dim is inside the image, so needs to be cropped
        c = tl.max(0)
        x = x.crop((*c, *c.add(sz).min(orig_sz)))
    if any(tl.lt(0)):
        # At least one dim is outside the image, so needs to be padded
        p = (-tl).max(0)
        f = (sz-orig_sz-p).max(0)
        x = tvpad(x, (*p, *f), padding_mode=_pad_modes[pad_mode])
    if resize_to is not None: x = x.resize(resize_to, resize_mode)
    return x

@patch
def _do_crop_pad(x:TensorPoint, sz, tl, orig_sz, pad_mode=PadMode.Zeros, resize_to=None, **kwargs):
    #assert pad_mode==PadMode.Zeros,"Only zero padding is supported for `TensorPoint` and `TensorBBox`"
    orig_sz,sz,tl = map(FloatTensor, (orig_sz,sz,tl))
    return TensorPoint((x+1)*orig_sz/sz - tl*2/sz - 1, sz=sz if resize_to is None else resize_to)

@patch
def _do_crop_pad(x:TensorBBox, sz, tl, orig_sz, pad_mode=PadMode.Zeros, resize_to=None, **kwargs):
    bbox = TensorPoint._do_crop_pad(x.view(-1,2), sz, tl, orig_sz, pad_mode, resize_to).view(-1,4)
    return TensorBBox(bbox, img_size=x.get_meta('img_size'))

@patch
def crop_pad(x:(TensorBBox,TensorPoint,Image.Image),
             sz, tl=None, orig_sz=None, pad_mode=PadMode.Zeros, resize_mode=Image.BILINEAR, resize_to=None):
    if isinstance(sz,int): sz = (sz,sz)
    orig_sz = Tuple(_get_sz(x) if orig_sz is None else orig_sz)
    sz,tl = Tuple(sz),Tuple(((_get_sz(x)-sz)//2) if tl is None else tl)
    return x._do_crop_pad(sz, tl, orig_sz=orig_sz, pad_mode=pad_mode, resize_mode=resize_mode, resize_to=resize_to)

# Cell
def _process_sz(size):
    if isinstance(size,int): size=(size,size)
    return Tuple(size[1],size[0])

def _get_sz(x):
    if isinstance(x, tuple): x = x[0]
    if not isinstance(x, Tensor): return Tuple(x.size)
    return Tuple(x.get_meta('img_size', x.get_meta('sz', (x.shape[-1], x.shape[-2]))))

# Cell
@delegates()
class CropPad(Transform):
    "Center crop or pad an image to `size`"
    order=0
    def __init__(self, size, pad_mode=PadMode.Zeros, **kwargs):
        super().__init__(**kwargs)
        self.size,self.pad_mode = _process_sz(size),pad_mode

    def encodes(self, x:(Image.Image,TensorBBox,TensorPoint)):
        orig_sz = _get_sz(x)
        tl = (orig_sz-self.size)//2
        return x.crop_pad(self.size, tl, orig_sz=orig_sz, pad_mode=self.pad_mode)

# Cell
@delegates()
class RandomCrop(RandTransform):
    "Randomly crop an image to `size`"
    split_idx = None
    order = 1
    def __init__(self, size, **kwargs):
        super().__init__(**kwargs)
        self.size = _process_sz(size)

    def before_call(self, b, split_idx):
        self.orig_sz = _get_sz(b)
        if split_idx: self.tl = (self.orig_sz-self.size)//2
        else: self.tl = Tuple(random.randint(0,self.orig_sz[0]-self.size[0]), random.randint(0,self.orig_sz[1]-self.size[1]))

    def encodes(self, x:(Image.Image,TensorBBox,TensorPoint)):
        return x.crop_pad(self.size, self.tl, orig_sz=self.orig_sz)

# Cell
class OldRandomCrop(CropPad):
    "Randomly crop an image to `size`"
    def before_call(self, b, split_idx):
        super().before_call(b, split_idx)
        w,h = self.orig_sz
        if not split_idx: self.tl = (random.randint(0,w-self.cp_size[0]), random.randint(0,h-self.cp_size[1]))

# Cell
mk_class('ResizeMethod', **{o:o.lower() for o in ['Squish', 'Crop', 'Pad']},
         doc="All possible resize method as attributes to get tab-completion and typo-proofing")

# Cell
@delegates()
class Resize(RandTransform):
    split_idx = None
    mode,mode_mask,order = Image.BILINEAR,Image.NEAREST,1
    "Resize image to `size` using `method`"
    def __init__(self, size, method=ResizeMethod.Crop, pad_mode=PadMode.Reflection,
                 resamples=(Image.BILINEAR, Image.NEAREST), **kwargs):
        super().__init__(**kwargs)
        self.size,self.pad_mode,self.method = _process_sz(size),pad_mode,method
        self.mode,self.mode_mask = resamples

    def before_call(self, b, split_idx):
        if self.method==ResizeMethod.Squish: return
        self.pcts = (0.5,0.5) if split_idx else (random.random(),random.random())

    def encodes(self, x:(Image.Image,TensorBBox,TensorPoint)):
        orig_sz = _get_sz(x)
        if self.method==ResizeMethod.Squish:
            return x.crop_pad(orig_sz, Tuple(0,0), orig_sz=orig_sz, pad_mode=self.pad_mode,
                   resize_mode=self.mode_mask if isinstance(x,PILMask) else self.mode, resize_to=self.size)

        w,h = orig_sz
        op = (operator.lt,operator.gt)[self.method==ResizeMethod.Pad]
        m = w/self.size[0] if op(w/self.size[0],h/self.size[1]) else h/self.size[1]
        cp_sz = (int(m*self.size[0]),int(m*self.size[1]))
        tl = Tuple(int(self.pcts[0]*(w-cp_sz[0])), int(self.pcts[1]*(h-cp_sz[1])))
        return x.crop_pad(cp_sz, tl, orig_sz=orig_sz, pad_mode=self.pad_mode,
                   resize_mode=self.mode_mask if isinstance(x,PILMask) else self.mode, resize_to=self.size)

# Cell
@delegates()
class RandomResizedCrop(RandTransform):
    "Picks a random scaled crop of an image and resize it to `size`"
    split_idx,order = None,1
    def __init__(self, size, min_scale=0.08, ratio=(3/4, 4/3), resamples=(Image.BILINEAR, Image.NEAREST),
                 val_xtra=0.14, **kwargs):
        super().__init__(**kwargs)
        self.size = _process_sz(size)
        store_attr(self, 'min_scale,ratio,val_xtra')
        self.mode,self.mode_mask = resamples

    def before_call(self, b, split_idx):
        w,h = self.orig_sz = _get_sz(b)
        if split_idx:
            xtra = math.ceil(max(*self.size[:2])*self.val_xtra/8)*8
            self.final_size = (self.size[0]+xtra, self.size[1]+xtra)
            self.tl,self.cp_size = (0,0),self.orig_sz
            return
        self.final_size = self.size
        for attempt in range(10):
            area = random.uniform(self.min_scale,1.) * w * h
            ratio = math.exp(random.uniform(math.log(self.ratio[0]), math.log(self.ratio[1])))
            nw = int(round(math.sqrt(area * ratio)))
            nh = int(round(math.sqrt(area / ratio)))
            if nw <= w and nh <= h:
                self.cp_size = (nw,nh)
                self.tl = random.randint(0,w-nw), random.randint(0,h - nh)
                return
        if   w/h < self.ratio[0]: self.cp_size = (w, int(w/self.ratio[0]))
        elif w/h > self.ratio[1]: self.cp_size = (int(h*self.ratio[1]), h)
        else:                     self.cp_size = (w, h)
        self.tl = ((w-self.cp_size[0])//2, (h-self.cp_size[1])//2)

    def encodes(self, x:(Image.Image,TensorBBox,TensorPoint)):
        res = x.crop_pad(self.cp_size, self.tl, orig_sz=self.orig_sz,
            resize_mode=self.mode_mask if isinstance(x,PILMask) else self.mode, resize_to=self.final_size)
        if self.final_size != self.size: res = res.crop_pad(self.size) #Validation set: one final center crop
        return res

# Cell
class RatioResize(Transform):
    'Resizes the biggest dimension of an image to `max_sz` maintaining the aspect ratio'
    order = 1
    def __init__(self, max_sz, resamples=(Image.BILINEAR, Image.NEAREST)):
        self.max_sz,self.resamples = max_sz,resamples

    def encodes(self, x:(Image.Image,TensorBBox,TensorPoint)):
        w,h = _get_sz(x)
        if w >= h: nw,nh = self.max_sz,h*self.max_sz/w
        else:      nw,nh = w*self.max_sz/h,self.max_sz
        return Resize(size=(int(nh),int(nw)), resamples=self.resamples)(x)

# Cell
def _init_mat(x):
    mat = torch.eye(3, device=x.device).float()
    return mat.unsqueeze(0).expand(x.size(0), 3, 3).contiguous()

# Cell
def _grid_sample(x, coords, mode='bilinear', padding_mode='reflection', align_corners=None):
    "Resample pixels in `coords` from `x` by `mode`, with `padding_mode` in ('reflection','border','zeros')."
    #coords = coords.permute(0, 3, 1, 2).contiguous().permute(0, 2, 3, 1) # optimize layout for grid_sample
    if mode=='bilinear': # hack to get smoother downwards resampling
        mn,mx = coords.min(),coords.max()
        # max amount we're affine zooming by (>1 means zooming in)
        z = 1/(mx-mn).item()*2
        # amount we're resizing by, with 100% extra margin
        d = min(x.shape[-2]/coords.shape[-2], x.shape[-1]/coords.shape[-1])/2
        # If we're resizing up by >200%, and we're zooming less than that, interpolate first
        if d>1 and d>z:
            x = F.interpolate(x, scale_factor=1/d, mode='area', recompute_scale_factor=True)
    return F.grid_sample(x, coords, mode=mode, padding_mode=padding_mode, align_corners=align_corners)

# Cell
@patch
def affine_coord(x: TensorImage, mat=None, coord_tfm=None, sz=None, mode='bilinear',
                 pad_mode=PadMode.Reflection, align_corners=True):
    if mat is None and coord_tfm is None and sz is None: return x
    size = tuple(x.shape[-2:]) if sz is None else (sz,sz) if isinstance(sz,int) else tuple(sz)
    if mat is None: mat = _init_mat(x)[:,:2]
    coords = F.affine_grid(mat, x.shape[:2] + size, align_corners=align_corners)
    if coord_tfm is not None: coords = coord_tfm(coords)
    return TensorImage(_grid_sample(x, coords, mode=mode, padding_mode=pad_mode, align_corners=align_corners))

@patch
def affine_coord(x: TensorMask, mat=None, coord_tfm=None, sz=None, mode='nearest',
                 pad_mode=PadMode.Reflection, align_corners=True):
    add_dim = (x.ndim==3)
    if add_dim: x = x[:,None]
    res = TensorImage.affine_coord(x.float(), mat, coord_tfm, sz, mode, pad_mode, align_corners).long()
    if add_dim: res = res[:,0]
    return TensorMask(res)

@patch
def affine_coord(x: TensorPoint, mat=None, coord_tfm=None, sz=None, mode='nearest',
                 pad_mode=PadMode.Zeros, align_corners=True):
    #assert pad_mode==PadMode.Zeros, "Only zero padding is supported for `TensorPoint` and `TensorBBox`"
    if sz is None: sz = x.get_meta('img_size')
    if coord_tfm is not None: x = coord_tfm(x, invert=True)
    if mat is not None: x = (x - mat[:,:,2].unsqueeze(1)) @ torch.inverse(mat[:,:,:2].transpose(1,2))
    return TensorPoint(x, sz=sz)

@patch
def affine_coord(x: TensorBBox, mat=None, coord_tfm=None, sz=None, mode='nearest',
                 pad_mode=PadMode.Zeros, align_corners=True):
    if mat is None and coord_tfm is None: return x
    if sz is None: sz = x.get_meta('img_size')
    bs,n = x.shape[:2]
    pnts = stack([x[...,:2], stack([x[...,0],x[...,3]],dim=2),
                  stack([x[...,2],x[...,1]],dim=2), x[...,2:]], dim=2)
    pnts = TensorPoint(pnts.view(bs, 4*n, 2), img_size=sz).affine_coord(mat, coord_tfm, sz, mode, pad_mode)
    pnts = pnts.view(bs, n, 4, 2)
    tl,dr = pnts.min(dim=2)[0],pnts.max(dim=2)[0]
    return TensorBBox(torch.cat([tl, dr], dim=2), img_size=sz)

# Cell
def _prepare_mat(x, mat):
    h,w = x.get_meta('img_size', x.shape[-2:])
    mat[:,0,1] *= h/w
    mat[:,1,0] *= w/h
    return mat[:,:2]

# Cell
class AffineCoordTfm(RandTransform):
    "Combine and apply affine and coord transforms"
    order,split_idx = 30,None
    def __init__(self, aff_fs=None, coord_fs=None, size=None, mode='bilinear', pad_mode=PadMode.Reflection,
                 mode_mask='nearest', align_corners=None):
        self.aff_fs,self.coord_fs = L(aff_fs),L(coord_fs)
        store_attr(self, 'size,mode,pad_mode,mode_mask,align_corners')
        self.cp_size = None if size is None else (size,size) if isinstance(size, int) else tuple(size)

    def before_call(self, b, split_idx):
        while isinstance(b, tuple): b = b[0]
        self.split_idx = split_idx
        self.do,self.mat = True,self._get_affine_mat(b)
        for t in self.coord_fs: t.before_call(b)

    def compose(self, tfm):
        "Compose `self` with another `AffineCoordTfm` to only do the interpolation step once"
        self.aff_fs   += tfm.aff_fs
        self.coord_fs += tfm.coord_fs

    def _get_affine_mat(self, x):
        aff_m = _init_mat(x)
        if self.split_idx: return _prepare_mat(x, aff_m)
        ms = [f(x) for f in self.aff_fs]
        ms = [m for m in ms if m is not None]
        for m in ms: aff_m = aff_m @ m
        return _prepare_mat(x, aff_m)

    def _encode(self, x, mode, reverse=False):
        coord_func = None if len(self.coord_fs)==0 or self.split_idx else partial(compose_tfms, tfms=self.coord_fs, reverse=reverse)
        return x.affine_coord(self.mat, coord_func, sz=self.size, mode=mode, pad_mode=self.pad_mode, align_corners=self.align_corners)

    def encodes(self, x:TensorImage): return self._encode(x, self.mode)
    def encodes(self, x:TensorMask):  return self._encode(x, self.mode_mask)
    def encodes(self, x:(TensorPoint, TensorBBox)): return self._encode(x, self.mode, reverse=True)

# Cell
class RandomResizedCropGPU(RandTransform):
    "Picks a random scaled crop of an image and resize it to `size`"
    split_idx,order = None,30
    def __init__(self, size, min_scale=0.08, ratio=(3/4, 4/3), mode='bilinear', valid_scale=1., **kwargs):
        super().__init__(**kwargs)
        self.size = (size,size) if isinstance(size, int) else size
        store_attr(self, 'min_scale,ratio,mode,valid_scale')

    def before_call(self, b, split_idx):
        self.do = True
        h,w = Tuple((b[0] if isinstance(b, tuple) else b).shape[-2:])
        for attempt in range(10):
            if split_idx: break
            area = random.uniform(self.min_scale,1.) * w * h
            ratio = math.exp(random.uniform(math.log(self.ratio[0]), math.log(self.ratio[1])))
            nw = int(round(math.sqrt(area * ratio)))
            nh = int(round(math.sqrt(area / ratio)))
            if nw <= w and nh <= h:
                self.cp_size = (nh,nw)
                self.tl = random.randint(0,h - nh),random.randint(0,w-nw)
                return
        if   w/h < self.ratio[0]: self.cp_size = (int(w/self.ratio[0]), w)
        elif w/h > self.ratio[1]: self.cp_size = (h, int(h*self.ratio[1]))
        else:                     self.cp_size = (h, w)
        if split_idx: self.cp_size = (int(self.cp_size[0]*self.valid_scale), int(self.cp_size[1]*self.valid_scale))
        self.tl = ((h-self.cp_size[0])//2,(w-self.cp_size[1])//2)

    def encodes(self, x:TensorImage):
        x = x[...,self.tl[0]:self.tl[0]+self.cp_size[0], self.tl[1]:self.tl[1]+self.cp_size[1]]
        return TensorImage(x).affine_coord(sz=self.size, mode=self.mode)

# Cell
def affine_mat(*ms):
    "Restructure length-6 vector `ms` into an affine matrix with 0,0,1 in the last line"
    return stack([stack([ms[0], ms[1], ms[2]], dim=1),
                  stack([ms[3], ms[4], ms[5]], dim=1),
                  stack([t0(ms[0]), t0(ms[0]), t1(ms[0])], dim=1)], dim=1)

# Cell
def mask_tensor(x, p=0.5, neutral=0., batch=False):
    "Mask elements of `x` with `neutral` with probability `1-p`"
    if p==1.: return x
    if batch: return x if random.random() < p else x.new_zeros(*x.size()) + neutral
    if neutral != 0: x.add_(-neutral)
    mask = x.new_empty(*x.size()).bernoulli_(p)
    x.mul_(mask)
    return x.add_(neutral) if neutral != 0 else x

# Cell
def _draw_mask(x, def_draw, draw=None, p=0.5, neutral=0., batch=False):
    if draw is None: draw=def_draw
    if callable(draw): res=draw(x)
    elif is_listy(draw):
        test_eq(len(draw), x.size(0))
        res = tensor(draw, dtype=x.dtype, device=x.device)
    else: res = x.new_zeros(x.size(0)) + draw
    return mask_tensor(res, p=p, neutral=neutral, batch=batch)

# Cell
def flip_mat(x, p=0.5, draw=None, batch=False):
    "Return a random flip matrix"
    def _def_draw(x): return x.new_ones(x.size(0))
    mask = x.new_ones(x.size(0)) - 2*_draw_mask(x, _def_draw, draw=draw, p=p, batch=batch)
    #mask = mask_tensor(-x.new_ones(x.size(0)), p=p, neutral=1.)
    return affine_mat(mask,     t0(mask), t0(mask),
                      t0(mask), t1(mask), t0(mask))

# Cell
def _get_default(x, mode=None, pad_mode=None):
    if mode is None: mode='bilinear' if isinstance(x, TensorMask) else 'bilinear'
    if pad_mode is None: pad_mode=PadMode.Zeros if isinstance(x, (TensorPoint, TensorBBox)) else PadMode.Reflection
    x0 = x[0] if isinstance(x, tuple) else x
    return x0,mode,pad_mode

# Cell
@patch
def flip_batch(x: (TensorImage,TensorMask,TensorPoint,TensorBBox), p=0.5, draw=None, size=None,
               mode=None, pad_mode=None, align_corners=True, batch=False):
    x0,mode,pad_mode = _get_default(x, mode, pad_mode)
    mat=flip_mat(x0, p=p, draw=draw, batch=batch)
    return x.affine_coord(mat=mat[:,:2], sz=size, mode=mode, pad_mode=pad_mode, align_corners=align_corners)

# Cell
def Flip(p=0.5, draw=None, size=None, mode='bilinear', pad_mode=PadMode.Reflection, align_corners=True, batch=False):
    "Randomly flip a batch of images with a probability `p`"
    return AffineCoordTfm(aff_fs=partial(flip_mat, p=p, draw=draw, batch=batch), size=size, mode=mode, pad_mode=pad_mode, align_corners=align_corners)

# Cell
class DeterministicDraw():
    def __init__(self, vals):
        store_attr(self, 'vals')
        self.count=-1

    def __call__(self, x):
        self.count += 1
        return x.new_zeros(x.size(0)) + self.vals[self.count%len(self.vals)]

# Cell
def DeterministicFlip(size=None, mode='bilinear', pad_mode=PadMode.Reflection, align_corners=True):
    "Flip the batch every other call"
    return Flip(p=1., draw=DeterministicDraw([0,1]), mode=mode, pad_mode=pad_mode, align_corners=align_corners)

# Cell
def dihedral_mat(x, p=0.5, draw=None, batch=False):
    "Return a random dihedral matrix"
    def _def_draw(x):   return torch.randint(0,8, (x.size(0),), device=x.device)
    def _def_draw_b(x): return random.randint(0,7) + x.new_zeros((x.size(0),)).long()
    idx = _draw_mask(x, _def_draw_b if batch else _def_draw, draw=draw, p=p, batch=batch).long()
    xs = tensor([1,-1,1,-1,-1,1,1,-1], device=x.device).gather(0, idx)
    ys = tensor([1,1,-1,1,-1,-1,1,-1], device=x.device).gather(0, idx)
    m0 = tensor([1,1,1,0,1,0,0,0], device=x.device).gather(0, idx)
    m1 = tensor([0,0,0,1,0,1,1,1], device=x.device).gather(0, idx)
    return affine_mat(xs*m0,  xs*m1,  t0(xs),
                      ys*m1,  ys*m0,  t0(xs)).float()

# Cell
@patch
def dihedral_batch(x: (TensorImage,TensorMask,TensorPoint,TensorBBox), p=0.5, draw=None, size=None,
                   mode=None, pad_mode=None, batch=False, align_corners=True):
    x0,mode,pad_mode = _get_default(x, mode, pad_mode)
    mat = _prepare_mat(x, dihedral_mat(x0, p=p, draw=draw, batch=batch))
    return x.affine_coord(mat=mat, sz=size, mode=mode, pad_mode=pad_mode, align_corners=align_corners)

# Cell
def Dihedral(p=0.5, draw=None, size=None, mode='bilinear', pad_mode=PadMode.Reflection, align_corners=None, batch=False):
    "Apply a random dihedral transformation to a batch of images with a probability `p`"
    f = partial(dihedral_mat, p=p, draw=draw, batch=batch)
    return AffineCoordTfm(aff_fs=f, size=size, mode=mode, pad_mode=pad_mode, align_corners=align_corners)

# Cell
def DeterministicDihedral(size=None, mode='bilinear', pad_mode=PadMode.Reflection, align_corners=None):
    "Flip the batch every other call"
    return Dihedral(p=1., draw=DeterministicDraw(list(range(8))), pad_mode=pad_mode, align_corners=align_corners)

# Cell
def rotate_mat(x, max_deg=10, p=0.5, draw=None, batch=False):
    "Return a random rotation matrix with `max_deg` and `p`"
    def _def_draw(x):   return x.new(x.size(0)).uniform_(-max_deg, max_deg)
    def _def_draw_b(x): return x.new_zeros(x.size(0)) + random.uniform(-max_deg, max_deg)
    thetas = _draw_mask(x, _def_draw_b if batch else _def_draw, draw=draw, p=p, batch=batch) * math.pi/180
    return affine_mat(thetas.cos(), thetas.sin(), t0(thetas),
                     -thetas.sin(), thetas.cos(), t0(thetas))

# Cell
@delegates(rotate_mat)
@patch
def rotate(x: (TensorImage,TensorMask,TensorPoint,TensorBBox), size=None, mode=None, pad_mode=None, align_corners=True, **kwargs):
    x0,mode,pad_mode = _get_default(x, mode, pad_mode)
    mat = _prepare_mat(x, rotate_mat(x0, **kwargs))
    return x.affine_coord(mat=mat, sz=size, mode=mode, pad_mode=pad_mode, align_corners=align_corners)

# Cell
def Rotate(max_deg=10, p=0.5, draw=None, size=None, mode='bilinear', pad_mode=PadMode.Reflection, align_corners=True, batch=False):
    "Apply a random rotation of at most `max_deg` with probability `p` to a batch of images"
    return AffineCoordTfm(partial(rotate_mat, max_deg=max_deg, p=p, draw=draw, batch=batch),
                          size=size, mode=mode, pad_mode=pad_mode, align_corners=align_corners)

# Cell
def zoom_mat(x, min_zoom=1., max_zoom=1.1, p=0.5, draw=None, draw_x=None, draw_y=None, batch=False):
    "Return a random zoom matrix with `max_zoom` and `p`"
    def _def_draw(x):       return x.new(x.size(0)).uniform_(min_zoom, max_zoom)
    def _def_draw_b(x):     return x.new_zeros(x.size(0)) + random.uniform(min_zoom, max_zoom)
    def _def_draw_ctr(x):   return x.new(x.size(0)).uniform_(0,1)
    def _def_draw_ctr_b(x): return x.new_zeros(x.size(0)) + random.uniform(0,1)
    assert(min_zoom<=max_zoom)
    s = 1/_draw_mask(x, _def_draw_b if batch else _def_draw, draw=draw, p=p, neutral=1., batch=batch)
    def_draw_c = _def_draw_ctr_b if batch else _def_draw_ctr
    col_pct = _draw_mask(x, def_draw_c, draw=draw_x, p=1., batch=batch)
    row_pct = _draw_mask(x, def_draw_c, draw=draw_y, p=1., batch=batch)
    col_c = (1-s) * (2*col_pct - 1)
    row_c = (1-s) * (2*row_pct - 1)
    return affine_mat(s,     t0(s), col_c,
                      t0(s), s,     row_c)

# Cell
@delegates(zoom_mat)
@patch
def zoom(x: (TensorImage,TensorMask,TensorPoint,TensorBBox), size=None, mode='bilinear', pad_mode=PadMode.Reflection,
         align_corners=True, **kwargs):
    x0,mode,pad_mode = _get_default(x, mode, pad_mode)
    return x.affine_coord(mat=zoom_mat(x0, **kwargs)[:,:2], sz=size, mode=mode, pad_mode=pad_mode, align_corners=align_corners)

# Cell
def Zoom(min_zoom=1., max_zoom=1.1, p=0.5, draw=None, draw_x=None, draw_y=None, size=None, mode='bilinear',
         pad_mode=PadMode.Reflection, batch=False, align_corners=True):
    "Apply a random zoom of at most `max_zoom` with probability `p` to a batch of images"
    return AffineCoordTfm(partial(zoom_mat, min_zoom=min_zoom, max_zoom=max_zoom, p=p, draw=draw, draw_x=draw_x, draw_y=draw_y, batch=batch),
                          size=size, mode=mode, pad_mode=pad_mode, align_corners=align_corners)

# Cell
def find_coeffs(p1, p2):
    "Find coefficients for warp tfm from `p1` to `p2`"
    m = []
    p = p1[:,0,0]
    #The equations we'll need to solve.
    for i in range(p1.shape[1]):
        m.append(stack([p2[:,i,0], p2[:,i,1], t1(p), t0(p), t0(p), t0(p), -p1[:,i,0]*p2[:,i,0], -p1[:,i,0]*p2[:,i,1]]))
        m.append(stack([t0(p), t0(p), t0(p), p2[:,i,0], p2[:,i,1], t1(p), -p1[:,i,1]*p2[:,i,0], -p1[:,i,1]*p2[:,i,1]]))
    #The 8 scalars we seek are solution of AX = B
    A = stack(m).permute(2, 0, 1)
    B = p1.view(p1.shape[0], 8, 1)
    return torch.solve(B,A)[0]

# Cell
def apply_perspective(coords, coeffs):
    "Apply perspective tranfom on `coords` with `coeffs`"
    sz = coords.shape
    coords = coords.view(sz[0], -1, 2)
    coeffs = torch.cat([coeffs, t1(coeffs[:,:1])], dim=1).view(coeffs.shape[0], 3,3)
    coords1 = coords @ coeffs[...,:2].transpose(1,2) + coeffs[...,2].unsqueeze(1)
    if (coords1[...,2]==0.).any(): return coords[...,:2].view(*sz)
    coords = coords1/coords1[...,2].unsqueeze(-1)
    return coords[...,:2].view(*sz)

# Cell
class _WarpCoord():
    def __init__(self, magnitude=0.2, p=0.5, draw_x=None, draw_y=None, batch=False):
        store_attr(self, "magnitude,p,draw_x,draw_y,batch")
        self.coeffs = None

    def _def_draw(self, x):
        if not self.batch: return x.new(x.size(0)).uniform_(-self.magnitude, self.magnitude)
        return x.new_zeros(x.size(0)) + random.uniform(-self.magnitude, self.magnitude)

    def before_call(self, x):
        x_t = _draw_mask(x, self._def_draw, self.draw_x, p=self.p, batch=self.batch)
        y_t = _draw_mask(x, self._def_draw, self.draw_y, p=self.p, batch=self.batch)
        orig_pts = torch.tensor([[-1,-1], [-1,1], [1,-1], [1,1]], dtype=x.dtype, device=x.device)
        self.orig_pts = orig_pts.unsqueeze(0).expand(x.size(0),4,2)
        targ_pts = stack([stack([-1-y_t, -1-x_t]), stack([-1+y_t, 1+x_t]),
                          stack([ 1+y_t, -1+x_t]), stack([ 1-y_t, 1-x_t])])
        self.targ_pts = targ_pts.permute(2,0,1)

    def __call__(self, x, invert=False):
        coeffs = find_coeffs(self.targ_pts, self.orig_pts) if invert else find_coeffs(self.orig_pts, self.targ_pts)
        return apply_perspective(x, coeffs)

# Cell
@delegates(_WarpCoord.__init__)
@patch
def warp(x:(TensorImage,TensorMask,TensorPoint,TensorBBox), size=None, mode='bilinear',
         pad_mode=PadMode.Reflection, align_corners=True, **kwargs):
    x0,mode,pad_mode = _get_default(x, mode, pad_mode)
    coord_tfm = _WarpCoord(**kwargs)
    coord_tfm.before_call(x0)
    return x.affine_coord(coord_tfm=coord_tfm, sz=size, mode=mode, pad_mode=pad_mode, align_corners=align_corners)

# Cell
def Warp(magnitude=0.2, p=0.5, draw_x=None, draw_y=None,size=None, mode='bilinear',
         pad_mode=PadMode.Reflection, batch=False, align_corners=True):
    "Apply perspective warping with `magnitude` and `p` on a batch of matrices"
    return AffineCoordTfm(coord_fs=_WarpCoord(magnitude=magnitude, p=p, draw_x=draw_x, draw_y=draw_y, batch=batch),
                          size=size, mode=mode, pad_mode=pad_mode, align_corners=align_corners)

# Cell
@patch
def lighting(x: TensorImage, func):
    return TensorImage(torch.sigmoid(func(logit(x))))

# Cell
class LightingTfm(RandTransform):
    "Apply `fs` to the logits"
    order = 40
    def __init__(self, fs): self.fs=L(fs)
    def before_call(self, b, split_idx):
        self.do = True
        while isinstance(b, tuple): b = b[0]
        for t in self.fs: t.before_call(b)

    def compose(self, tfm):
        "Compose `self` with another `LightingTransform`"
        self.fs += tfm.fs

    def encodes(self,x:TensorImage): return x.lighting(partial(compose_tfms, tfms=self.fs))

# Cell
class _BrightnessLogit():
    def __init__(self, max_lighting=0.2, p=0.75, draw=None, batch=False):
        store_attr(self, 'max_lighting,p,draw,batch')

    def _def_draw(self, x):
        if not self.batch: return x.new(x.size(0)).uniform_(0.5*(1-self.max_lighting), 0.5*(1+self.max_lighting))
        return x.new_zeros(x.size(0)) + random.uniform(0.5*(1-self.max_lighting), 0.5*(1+self.max_lighting))

    def before_call(self, x):
        self.change = _draw_mask(x, self._def_draw, draw=self.draw, p=self.p, neutral=0.5, batch=self.batch)

    def __call__(self, x): return x.add_(logit(self.change[:,None,None,None]))

# Cell
@delegates(_BrightnessLogit.__init__)
@patch
def brightness(x: TensorImage, **kwargs):
    func = _BrightnessLogit(**kwargs)
    func.before_call(x)
    return x.lighting(func)

# Cell
def Brightness(max_lighting=0.2, p=0.75, draw=None, batch=False):
    "Apply change in brightness of `max_lighting` to batch of images with probability `p`."
    return LightingTfm(_BrightnessLogit(max_lighting, p, draw, batch))

# Cell
class _ContrastLogit():
    def __init__(self, max_lighting=0.2, p=0.75, draw=None, batch=False):
        store_attr(self, 'max_lighting,p,draw,batch')

    def _def_draw(self, x):
        if not self.batch: res = x.new(x.size(0)).uniform_(math.log(1-self.max_lighting), -math.log(1-self.max_lighting))
        else: res = x.new_zeros(x.size(0)) + random.uniform(math.log(1-self.max_lighting), -math.log(1-self.max_lighting))
        return torch.exp(res)

    def before_call(self, x):
        self.change = _draw_mask(x, self._def_draw, draw=self.draw, p=self.p, neutral=1., batch=self.batch)

    def __call__(self, x): return x.mul_(self.change[:,None,None,None])

# Cell
@delegates(_ContrastLogit.__init__)
@patch
def contrast(x: TensorImage, **kwargs):
    func = _ContrastLogit(**kwargs)
    func.before_call(x)
    return x.lighting(func)

# Cell
def Contrast(max_lighting=0.2, p=0.75, draw=None, batch=False):
    "Apply change in contrast of `max_lighting` to batch of images with probability `p`."
    return LightingTfm(_ContrastLogit(max_lighting, p, draw, batch))

# Cell
def cutout_gaussian(x, areas):
    "Replace all `areas` in `x` with N(0,1) noise"
    chan,img_h,img_w = x.shape[-3:]
    for rl,rh,cl,ch in areas: x[..., rl:rh, cl:ch].normal_()
    return x

# Cell
def norm_apply_denorm(x, f, nrm):
    "Normalize `x` with `nrm`, then apply `f`, then denormalize"
    y = f(nrm(x.clone()))
    return nrm.decode(y).clamp(0,1)

# Cell
def _slice(area, sz):
    bound = int(round(math.sqrt(area)))
    loc = random.randint(0, max(sz-bound, 0))
    return loc,loc+bound

# Cell
class RandomErasing(RandTransform):
    "Randomly selects a rectangle region in an image and randomizes its pixels."
    order = 100 # After Normalize
    def __init__(self, p=0.5, sl=0., sh=0.3, min_aspect=0.3, max_count=1):
        super().__init__(p=p)
        log_ratio = (math.log(min_aspect), math.log(1/min_aspect))
        store_attr(self, 'sl,sh,log_ratio,max_count')

    def _bounds(self, area, img_h, img_w):
        r_area = random.uniform(self.sl,self.sh) * area
        aspect = math.exp(random.uniform(*self.log_ratio))
        return _slice(r_area*aspect, img_h) + _slice(r_area/aspect, img_w)

    def encodes(self,x:TensorImage):
        count = random.randint(1, self.max_count)
        _,img_h,img_w = x.shape[-3:]
        area = img_h*img_w/count
        areas = [self._bounds(area, img_h, img_w) for _ in range(count)]
        return cutout_gaussian(x, areas)

# Cell
def _compose_same_tfms(tfms):
    tfms = L(tfms)
    if len(tfms) == 0: return None
    res = tfms[0]
    for tfm in tfms[1:]: res.compose(tfm)
    return res

# Cell
def setup_aug_tfms(tfms):
    "Go through `tfms` and combines together affine/coord or lighting transforms"
    aff_tfms = [tfm for tfm in tfms if isinstance(tfm, AffineCoordTfm)]
    lig_tfms = [tfm for tfm in tfms if isinstance(tfm, LightingTfm)]
    others = [tfm for tfm in tfms if tfm not in aff_tfms+lig_tfms]
    aff_tfm,lig_tfm =  _compose_same_tfms(aff_tfms),_compose_same_tfms(lig_tfms)
    res = [aff_tfm] if aff_tfm is not None else []
    if lig_tfm is not None: res.append(lig_tfm)
    return res + others

# Cell
def aug_transforms(mult=1.0, do_flip=True, flip_vert=False, max_rotate=10., min_zoom=1., max_zoom=1.1,
                   max_lighting=0.2, max_warp=0.2, p_affine=0.75, p_lighting=0.75, xtra_tfms=None, size=None,
                   mode='bilinear', pad_mode=PadMode.Reflection, align_corners=True, batch=False, min_scale=1.):
    "Utility func to easily create a list of flip, rotate, zoom, warp, lighting transforms."
    res,tkw = [],dict(size=size if min_scale==1. else None, mode=mode, pad_mode=pad_mode, batch=batch, align_corners=align_corners)
    max_rotate,max_lighting,max_warp = array([max_rotate,max_lighting,max_warp])*mult
    if do_flip: res.append(Dihedral(p=0.5, **tkw) if flip_vert else Flip(p=0.5, **tkw))
    if max_warp:   res.append(Warp(magnitude=max_warp, p=p_affine, **tkw))
    if max_rotate: res.append(Rotate(max_deg=max_rotate, p=p_affine, **tkw))
    if min_zoom<1 or max_zoom>1: res.append(Zoom(min_zoom=min_zoom, max_zoom=max_zoom, p=p_affine, **tkw))
    if max_lighting:
        res.append(Brightness(max_lighting=max_lighting, p=p_lighting, batch=batch))
        res.append(Contrast(max_lighting=max_lighting, p=p_lighting, batch=batch))
    if min_scale!=1.: xtra_tfms = RandomResizedCropGPU(size, min_scale=min_scale, ratio=(1,1)) + L(xtra_tfms)
    return setup_aug_tfms(res + L(xtra_tfms))