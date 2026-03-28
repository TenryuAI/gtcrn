import torch
import torch.nn as nn

def fuse_conv_bn(conv, bn):
    """Fuse nn.Conv2d and nn.BatchNorm2d into a single Conv2d."""
    fusedconv = nn.Conv2d(
        conv.in_channels, conv.out_channels,
        kernel_size=conv.kernel_size, stride=conv.stride,
        padding=conv.padding, dilation=conv.dilation,
        groups=conv.groups, bias=True
    )
    with torch.no_grad():
        scale = bn.weight / torch.sqrt(bn.running_var + bn.eps)
        w_conv = conv.weight.clone().view(conv.out_channels, -1)
        w_bn = torch.diag(scale)
        fusedconv.weight.copy_(torch.mm(w_bn, w_conv).view(fusedconv.weight.size()))
        b_conv = torch.zeros(conv.out_channels) if conv.bias is None else conv.bias.clone()
        b_bn = bn.bias - bn.weight * bn.running_mean / torch.sqrt(bn.running_var + bn.eps)
        fusedconv.bias.copy_(scale * b_conv + b_bn)
    return fusedconv

def fuse_convtranspose_bn(convt, bn):
    """Fuse nn.ConvTranspose2d and nn.BatchNorm2d into a single ConvTranspose2d."""
    fusedconvt = nn.ConvTranspose2d(
        convt.in_channels, convt.out_channels,
        kernel_size=convt.kernel_size, stride=convt.stride,
        padding=convt.padding, output_padding=convt.output_padding,
        groups=convt.groups, bias=True, dilation=convt.dilation
    )
    with torch.no_grad():
        scale = bn.weight / torch.sqrt(bn.running_var + bn.eps)
        groups = convt.groups
        in_c, out_c = convt.in_channels, convt.out_channels
        # ConvTranspose2d weight: (in_channels, out_channels/groups, H, W)
        # BN normalizes each output channel, scale shape: (out_channels,)
        w = convt.weight.clone().view(groups, in_c // groups, out_c // groups, *convt.weight.shape[2:])
        s = scale.view(groups, 1, out_c // groups, 1, 1)
        w = (w * s).view(in_c, out_c // groups, *convt.weight.shape[2:])
        fusedconvt.weight.copy_(w)
        b_convt = torch.zeros(out_c) if convt.bias is None else convt.bias.clone()
        b_bn = bn.bias - bn.weight * bn.running_mean / torch.sqrt(bn.running_var + bn.eps)
        fusedconvt.bias.copy_(scale * b_convt + b_bn)
    return fusedconvt

def fuse_model(m):
    for child_name, child in m.named_children():
        # ConvBlock: has .conv (Conv2d or ConvTranspose2d) and .bn (BatchNorm2d)
        if hasattr(child, 'conv') and hasattr(child, 'bn') and isinstance(child.bn, nn.BatchNorm2d):
            if isinstance(child.conv, nn.Conv2d):
                child.conv = fuse_conv_bn(child.conv, child.bn)
                child.bn = nn.Identity()
            elif isinstance(child.conv, nn.ConvTranspose2d):
                child.conv = fuse_convtranspose_bn(child.conv, child.bn)
                child.bn = nn.Identity()

        # StreamGTConvBlock: .point_conv1 (Conv2d or ConvTranspose2d) + .point_bn1 (BatchNorm2d)
        if hasattr(child, 'point_conv1') and hasattr(child, 'point_bn1') and isinstance(child.point_bn1, nn.BatchNorm2d):
            if isinstance(child.point_conv1, nn.ConvTranspose2d):
                child.point_conv1 = fuse_convtranspose_bn(child.point_conv1, child.point_bn1)
            else:
                child.point_conv1 = fuse_conv_bn(child.point_conv1, child.point_bn1)
            child.point_bn1 = nn.Identity()

        # StreamGTConvBlock: .depth_conv + .depth_bn (BatchNorm2d)
        # depth_conv can be: nn.Conv2d, StreamConv2d, or StreamConvTranspose2d
        if hasattr(child, 'depth_conv') and hasattr(child, 'depth_bn') and isinstance(child.depth_bn, nn.BatchNorm2d):
            dc = child.depth_conv
            if isinstance(dc, nn.Conv2d):
                # Non-streaming regular Conv2d
                child.depth_conv = fuse_conv_bn(dc, child.depth_bn)
            elif hasattr(dc, 'Conv2d') and isinstance(dc.Conv2d, nn.Conv2d):
                # StreamConv2d: wraps an nn.Conv2d in self.Conv2d
                dc.Conv2d = fuse_conv_bn(dc.Conv2d, child.depth_bn)
            elif hasattr(dc, 'ConvTranspose2d') and isinstance(dc.ConvTranspose2d, nn.Conv2d):
                # StreamConvTranspose2d: internally uses nn.Conv2d named ConvTranspose2d
                dc.ConvTranspose2d = fuse_conv_bn(dc.ConvTranspose2d, child.depth_bn)
            child.depth_bn = nn.Identity()

        # StreamGTConvBlock: .point_conv2 (Conv2d or ConvTranspose2d) + .point_bn2 (BatchNorm2d)
        if hasattr(child, 'point_conv2') and hasattr(child, 'point_bn2') and isinstance(child.point_bn2, nn.BatchNorm2d):
            if isinstance(child.point_conv2, nn.ConvTranspose2d):
                child.point_conv2 = fuse_convtranspose_bn(child.point_conv2, child.point_bn2)
            else:
                child.point_conv2 = fuse_conv_bn(child.point_conv2, child.point_bn2)
            child.point_bn2 = nn.Identity()

        fuse_model(child)
