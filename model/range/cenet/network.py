import torch.nn as nn
import torch
from torch.nn import functional as F


def conv3x3(
    in_planes: int, out_planes: int, stride: int = 1,
    groups: int = 1, dilation: int = 1,
):
    return nn.Conv2d(
        in_planes, out_planes,
        kernel_size=3, stride=stride,
        padding=dilation, groups=groups,
        bias=False, dilation=dilation,
    )


def conv1x1(
    in_planes: int, out_planes: int, stride: int = 1,
):
    return nn.Conv2d(
        in_planes, out_planes,
        kernel_size=1, stride=stride,
        bias=False,
    )


class BasicConv2d(nn.Module):
    def __init__(
        self,
        in_planes: int,
        out_planes: int,
        kernel_size: int,
        stride: int = 1,
        padding: int = 0,
        dilation: int = 1,
        relu: bool = True
    ):
        super(BasicConv2d, self).__init__()
        self.relu = relu
        self.conv = nn.Conv2d(
            in_planes, out_planes,
            kernel_size=kernel_size, stride=stride,
            padding=padding, dilation=dilation, bias=False
        )
        self.bn = nn.BatchNorm2d(out_planes)
        if self.relu:
            self.relu = nn.LeakyReLU()

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        if self.relu:
            x = self.relu(x)
        return x


class Final_Model(nn.Module):

    def __init__(self, backbone_net, semantic_head):
        super(Final_Model, self).__init__()
        self.backend = backbone_net
        self.semantic_head = semantic_head

    def forward(self, x):
        middle_feature_maps = self.backend(x)
        semantic_output = self.semantic_head(middle_feature_maps)

        return semantic_output


class BasicBlock(nn.Module):
    expansion = 1
    def __init__(
        self,
        inplanes: int,
        planes: int,
        stride: int = 1,
        downsample = None,
        groups: int = 1,
        base_width: int = 64,
        dilation: int = 1,
        if_BN: bool = False
    ):
        super(BasicBlock, self).__init__()
        self.if_BN = if_BN
        if self.if_BN:
            norm_layer = nn.BatchNorm2d
        if groups != 1 or base_width != 64:
            raise ValueError('BasicBlock only supports groups=1 and base_width=64')
        if dilation > 1:
            raise NotImplementedError("Dilation > 1 not supported in BasicBlock")

        self.conv1 = conv3x3(inplanes, planes, stride)
        if self.if_BN:
            self.bn1 = norm_layer(planes)
        self.relu = nn.LeakyReLU()

        self.conv2 = conv3x3(planes, planes)
        if self.if_BN:
            self.bn2 = norm_layer(planes)
        
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        identity = x

        out = self.conv1(x)
        if self.if_BN:
            out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        if self.if_BN:
            out = self.bn2(out)
        if self.downsample is not None:
            identity = self.downsample(x)
        out += identity
        out = self.relu(out)
        return out


class CENet(nn.Module):
    def __init__(
        self,
        num_cls: int,
        aux: bool,
        block = BasicBlock,
        layers: list = [3, 4, 6, 3],
        if_BN: bool = True,
        norm_layer = None,
        groups: int = 1,
        width_per_group: int = 64
    ):
        super(CENet, self).__init__()
        if norm_layer is None:
            norm_layer = nn.BatchNorm2d
        self._norm_layer = norm_layer
        self.if_BN = if_BN
        self.dilation = 1
        self.aux = aux

        self.groups = groups
        self.base_width = width_per_group

        self.conv1 = BasicConv2d(6, 64, kernel_size=3, padding=1)
        self.conv2 = BasicConv2d(64, 128, kernel_size=3, padding=1)
        self.conv3 = BasicConv2d(128, 128, kernel_size=3, padding=1)

        self.inplanes = 128

        self.layer1 = self._make_layer(block, 128, layers[0])
        self.layer2 = self._make_layer(block, 128, layers[1], stride=2)
        self.layer3 = self._make_layer(block, 128, layers[2], stride=2)
        self.layer4 = self._make_layer(block, 128, layers[3], stride=2)

        self.conv_1 = BasicConv2d(640, 256, kernel_size=3, padding=1)
        self.conv_2 = BasicConv2d(256, 128, kernel_size=3, padding=1)
        self.semantic_output = nn.Conv2d(128, num_cls, 1)

        if self.aux:
            self.aux_head1 = nn.Conv2d(128, num_cls, 1)
            self.aux_head2 = nn.Conv2d(128, num_cls, 1)
            self.aux_head3 = nn.Conv2d(128, num_cls, 1)

    def _make_layer(self, block, planes, blocks, stride=1, dilate=False):
        norm_layer = self._norm_layer
        downsample = None
        previous_dilation = self.dilation
        if dilate:
            self.dilation *= stride
            stride = 1
        if stride != 1 or self.inplanes != planes * block.expansion:
            if self.if_BN:
                downsample = nn.Sequential(
                    conv1x1(self.inplanes, planes * block.expansion, stride),
                    norm_layer(planes * block.expansion),
                )
            else:
                downsample = nn.Sequential(
                    conv1x1(self.inplanes, planes * block.expansion, stride)
                )

        layers = []
        layers.append(block(self.inplanes, planes, stride, downsample, self.groups,
                            self.base_width, previous_dilation, if_BN=self.if_BN))
        self.inplanes = planes * block.expansion
        for _ in range(1, blocks):
            layers.append(block(self.inplanes, planes, groups=self.groups,
                                base_width=self.base_width, dilation=self.dilation,
                                if_BN=self.if_BN))

        return nn.Sequential(*layers)

    def forward(self, x):  # [bs, 6,  H, W]

        x = self.conv1(x)  # [bs, 64,  H, W]
        x = self.conv2(x)  # [bs, 128, H, W]
        x = self.conv3(x)  # [bs, 128, H, W]

        x_1 = self.layer1(x)    # [bs, 128, H, W]
        x_2 = self.layer2(x_1)  # [bs, 128, H/2, W/2]
        x_3 = self.layer3(x_2)  # [bs, 128, H/4, W/4]
        x_4 = self.layer4(x_3)  # [bs, 128, H/8, W/8]

        res_2 = F.interpolate(x_2, size=x.size()[2:], mode='bilinear', align_corners=True)  # [bs, 128, H, W]
        res_3 = F.interpolate(x_3, size=x.size()[2:], mode='bilinear', align_corners=True)  # [bs, 128, H, W]
        res_4 = F.interpolate(x_4, size=x.size()[2:], mode='bilinear', align_corners=True)  # [bs, 128, H, W]
        res = [x, x_1, res_2, res_3, res_4]

        out = torch.cat(res, dim=1)  # [bs, 640, H, W]
        out = self.conv_1(out)  # [bs, 256, H, W]
        out = self.conv_2(out)  # [bs, 128, H, W]
        out = self.semantic_output(out)  # [bs, cls, H, W]

        if self.aux:
            res_2 = self.aux_head1(res_2)  # [bs, 128, H, W] -> [bs, cls, H, W]
            res_2 = F.softmax(res_2, dim=1)

            res_3 = self.aux_head2(res_3)  # [bs, 128, H, W] -> [bs, cls, H, W]
            res_3 = F.softmax(res_3, dim=1)

            res_4 = self.aux_head3(res_4)  # [bs, 128, H, W] -> [bs, cls, H, W]
            res_4 = F.softmax(res_4, dim=1)

        if self.aux and self.training:
            return [out, res_2, res_3, res_4]
        else:
            return out
