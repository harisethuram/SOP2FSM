import torch

embeds = torch.load("data/embeddings.pt")
print(embeds.shape)
embeds = embeds[:6, :]
print(embeds.shape)
torch.save(embeds, "data/embeddings.pt")